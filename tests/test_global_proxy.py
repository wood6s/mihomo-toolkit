from contextlib import ExitStack, redirect_stdout
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


proxy = load("global_proxy", ROOT / "bin/mihomo-global-proxy")
startup = load("configure_user", ROOT / "scripts/configure-user.py")


class GlobalProxyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.defaults = self.directory / "mihomo-toolkit/proxy-defaults.sh"
        self.environment = self.directory / "environment.d/90-mihomo-proxy.conf"
        self.settings = {("org.gnome.system.proxy", "mode"): "'none'"}
        self.session = {"HTTPS_PROXY": "http://previous.invalid:8080"}
        self.session_available = True
        self.fail_sync = False
        self.ignore_mode_write = False
        self.calls = []
        self.stack.enter_context(mock.patch.object(proxy, "DEFAULTS", self.defaults))
        self.stack.enter_context(mock.patch.object(proxy, "ENVIRONMENT", self.environment))
        self.stack.enter_context(mock.patch.object(proxy, "desktop_command", return_value=("gsettings",)))
        self.stack.enter_context(mock.patch.object(proxy.shutil, "which", return_value="/usr/bin/mock"))
        self.stack.enter_context(mock.patch.object(proxy, "run", side_effect=self.fake_run))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def fake_run(self, *args, check=True):
        self.calls.append(args)
        stdout = ""
        returncode = 0
        if args[0] == "gsettings":
            action, schema, key = args[1:4]
            if action == "set":
                if not (key == "mode" and self.ignore_mode_write):
                    self.settings[(schema, key)] = args[4]
            elif action == "get":
                stdout = self.settings.get((schema, key), "0" if key == "port" else "''") + "\n"
        elif args[:3] == ("systemctl", "--user", "show-environment"):
            returncode = 0 if self.session_available else 1
            stdout = "".join(f"{key}={value}\n" for key, value in self.session.items())
        elif args[0] == "dbus-update-activation-environment":
            if self.fail_sync:
                self.fail_sync = False
                raise subprocess.CalledProcessError(1, args, stderr="session update failed")
            self.session.update(item.split("=", 1) for item in args[2:])
        elif args[:3] == ("systemctl", "--user", "unset-environment"):
            for key in args[3:]:
                self.session.pop(key, None)
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)

    def shell_environment(self):
        result = os.environ.copy()
        result.update({key: "http://stale.invalid:8080" for key in proxy.VALUES})
        result["XDG_CONFIG_HOME"] = str(self.directory)
        return result

    def assert_shell(self, command):
        result = subprocess.run(["sh", "-c", '. "$1"; ' + command, "check", str(self.defaults)],
                                env=self.shell_environment(), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_enable_applies_desktop_new_shell_and_user_service(self):
        proxy.switch(True)
        self.assertEqual(self.settings[("org.gnome.system.proxy", "mode")], "'manual'")
        self.assertEqual(self.settings[("org.gnome.system.proxy.https", "port")], "7890")
        self.assertEqual(self.session["ALL_PROXY"], "socks5h://127.0.0.1:7890")
        self.assertIn("HTTPS_PROXY=http://127.0.0.1:7890\n", self.environment.read_text())
        self.assert_shell('test "$https_proxy" = http://127.0.0.1:7890 && '
                          'test "$ALL_PROXY" = socks5h://127.0.0.1:7890')

    def test_disable_removes_inherited_proxy_and_keeps_service_running(self):
        proxy.switch(True)
        self.calls.clear()
        proxy.switch(False)
        self.assertEqual(self.settings[("org.gnome.system.proxy", "mode")], "'none'")
        self.assertTrue(all(self.session[key] == "" for key in proxy.VALUES))
        self.assert_shell('test -z "${HTTP_PROXY-}${HTTPS_PROXY-}${ALL_PROXY-}'
                          '${http_proxy-}${https_proxy-}${all_proxy-}${NO_PROXY-}${no_proxy-}"')
        self.assertFalse(any("stop" in args or "disable" in args for args in self.calls))

    def test_disable_still_works_with_invalid_new_endpoint(self):
        proxy.switch(True)
        with mock.patch.object(proxy, "HTTP", "broken"):
            proxy.switch(False)
        self.assertEqual(proxy.preference(), "已关闭")

    def test_session_failure_restores_files_desktop_and_previous_environment(self):
        self.defaults.parent.mkdir(parents=True)
        self.defaults.write_text("# previously configured\n")
        previous_session = self.session.copy()
        self.fail_sync = True
        with self.assertRaises(subprocess.CalledProcessError):
            proxy.switch(True)
        self.assertEqual(self.defaults.read_text(), "# previously configured\n")
        self.assertFalse(self.environment.exists())
        self.assertEqual(self.settings[("org.gnome.system.proxy", "mode")], "'none'")
        self.assertEqual(self.session, previous_session)

    def test_failed_file_write_restores_desktop_and_removes_partial_files(self):
        original = proxy.write_atomic

        def fail_environment(path, text):
            if path == self.environment:
                raise OSError("disk full")
            original(path, text)

        with mock.patch.object(proxy, "write_atomic", side_effect=fail_environment):
            with self.assertRaisesRegex(OSError, "disk full"):
                proxy.switch(True)
        self.assertFalse(self.defaults.exists())
        self.assertFalse(self.environment.exists())
        self.assertEqual(self.settings[("org.gnome.system.proxy", "mode")], "'none'")

    def test_unapplied_desktop_write_is_detected_before_defaults_change(self):
        self.ignore_mode_write = True
        with self.assertRaisesRegex(RuntimeError, "写入未生效"):
            proxy.switch(True)
        self.assertFalse(self.defaults.exists())

    def test_headless_without_user_session_persists_defaults(self):
        self.session_available = False
        with mock.patch.object(proxy, "desktop_command", return_value=None):
            proxy.switch(True)
            proxy.status()
        self.assertEqual(proxy.preference(), "已开启")
        self.assert_shell('test "$HTTP_PROXY" = http://127.0.0.1:7890')
        self.assertFalse(any(args[0] in ("gsettings", "dbus-update-activation-environment")
                             for args in self.calls))

    def test_configured_ports_match_desktop_and_shell(self):
        values = {**proxy.VALUES, "HTTP_PROXY": "http://127.0.0.2:8000",
                  "HTTPS_PROXY": "http://127.0.0.2:8000", "ALL_PROXY": "socks5h://127.0.0.3:9000"}
        values.update({key.lower(): value for key, value in list(values.items()) if key.isupper()})
        with (mock.patch.object(proxy, "HTTP", values["HTTP_PROXY"]),
              mock.patch.object(proxy, "SOCKS", values["ALL_PROXY"]),
              mock.patch.object(proxy, "VALUES", values)):
            proxy.switch(True)
        self.assertEqual(self.settings[("org.gnome.system.proxy.http", "port")], "8000")
        self.assertEqual(self.settings[("org.gnome.system.proxy.socks", "host")], "'127.0.0.3'")
        self.assert_shell('test "$HTTPS_PROXY" = http://127.0.0.2:8000 && '
                          'test "$ALL_PROXY" = socks5h://127.0.0.3:9000')

    def test_zsh_reload_preserves_terminal_opt_out(self):
        proxy.switch(True)
        reference = self.directory / "reference"
        reference.write_text("#!/bin/sh\nprintf '0\\n'\n")
        reference.chmod(0o755)
        environment = self.shell_environment()
        environment["MIHOMO_REF"] = str(reference)
        command = '''
            source "$1"
            [[ "$_MIHOMO_PROXY_ACTIVE" == 1 && "$https_proxy" == http://127.0.0.1:7890 ]] || exit 10
            proxy_off >/dev/null || exit 11
            source "$1"
            [[ "$_MIHOMO_PROXY_ACTIVE" == 0 && -z "${https_proxy-}" ]] || exit 12
        '''
        result = subprocess.run(["zsh", "-fc", command, "check", str(ROOT / "shell/mihomo-control.zsh")],
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class StartupTests(unittest.TestCase):
    def test_install_is_repeatable_and_remove_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            original = "# personal settings\nexport EDITOR=vim\n"
            (target / ".zshenv").write_text(original)
            (target / ".bash_profile").write_text(original)
            startup.configure(target, True)
            first = (target / ".zshenv").read_text()
            startup.configure(target, True)
            self.assertEqual((target / ".zshenv").read_text(), first)
            self.assertEqual(first.count(startup.BEGIN), 1)
            self.assertIn(startup.BEGIN, (target / ".bash_profile").read_text())
            self.assertFalse((target / ".bash_login").exists())
            startup.configure(target, False)
            self.assertEqual((target / ".zshenv").read_text().strip(), original.strip())
            self.assertNotIn(startup.BEGIN, (target / ".bash_profile").read_text())

    def test_startup_symlink_target_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            real = target / "shared-startup"
            real.write_text("# managed elsewhere\n")
            (target / ".zshenv").symlink_to(real)
            with mock.patch("sys.stderr", new=io.StringIO()):
                startup.configure(target, True)
            self.assertEqual(real.read_text(), "# managed elsewhere\n")


if __name__ == "__main__":
    unittest.main()
