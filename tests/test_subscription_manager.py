from __future__ import annotations

from contextlib import redirect_stdout
import io
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "sbin" / "mihomo-subscription-manager"
LOADER = SourceFileLoader("mihomo_subscription_manager", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"无法加载 {MODULE_PATH}")
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class SubscriptionManagerTests(unittest.TestCase):
    def test_validate_url_accepts_https(self) -> None:
        self.assertEqual(
            manager.validate_url("https://example.com/subscription\n"),
            "https://example.com/subscription",
        )

    def test_validate_url_rejects_http_and_credentials(self) -> None:
        with self.assertRaises(manager.ManagerError):
            manager.validate_url("http://example.com/subscription")
        with self.assertRaises(manager.ManagerError):
            manager.validate_url("https://user:pass@example.com/subscription")

    def test_render_adds_marked_provider_and_rewrites_match(self) -> None:
        original = (REPO_ROOT / "config" / "config.example.yaml").read_text(
            encoding="utf-8"
        )
        label = "示例订阅"
        state = {
            "version": 1,
            "target_group": "",
            "subscriptions": [
                {
                    "id": manager.subscription_id(label),
                    "label": label,
                    "url": "https://example.com/subscription",
                }
            ],
        }

        rendered = manager.render_config(original, state)
        parsed = yaml.safe_load(rendered)

        self.assertIn(manager.BEGIN_PROVIDERS, rendered)
        self.assertIn(manager.BEGIN_GROUPS, rendered)
        self.assertEqual(state["existing_group"], "默认代理")
        self.assertEqual(state["entry_group"], "代理选择")
        self.assertTrue(state["include_existing_group"])
        self.assertEqual(
            list(parsed["proxy-providers"]), [manager.subscription_id(label)]
        )
        self.assertIn("MATCH,代理选择", parsed["rules"])

        entry = next(
            group for group in parsed["proxy-groups"] if group["name"] == "代理选择"
        )
        self.assertEqual(entry["proxies"], ["默认代理", label])

    def test_render_can_remove_existing_group_from_entry(self) -> None:
        original = (REPO_ROOT / "config" / "config.example.yaml").read_text(
            encoding="utf-8"
        )
        label = "示例订阅"
        state = {
            "version": 1,
            "target_group": "",
            "include_existing_group": False,
            "subscriptions": [
                {
                    "id": manager.subscription_id(label),
                    "label": label,
                    "url": "https://example.com/subscription",
                }
            ],
        }

        rendered = manager.render_config(original, state)
        parsed = yaml.safe_load(rendered)
        entry = next(
            group for group in parsed["proxy-groups"] if group["name"] == "代理选择"
        )

        self.assertEqual(entry["proxies"], [label])
        self.assertIn(
            "默认代理",
            [group["name"] for group in parsed["proxy-groups"]],
        )

    def test_render_uses_direct_when_all_proxy_entries_are_removed(self) -> None:
        original = (REPO_ROOT / "config" / "config.example.yaml").read_text(
            encoding="utf-8"
        )
        state = {
            "version": 1,
            "target_group": "",
            "include_existing_group": False,
            "subscriptions": [],
        }

        rendered = manager.render_config(original, state)
        parsed = yaml.safe_load(rendered)
        entry = next(
            group for group in parsed["proxy-groups"] if group["name"] == "代理选择"
        )

        self.assertEqual(entry["proxies"], ["DIRECT"])
        self.assertFalse(state["include_existing_group"])

    def test_names_include_removable_existing_group(self) -> None:
        state = {
            "version": 1,
            "existing_group": "默认代理",
            "subscriptions": [
                {
                    "id": manager.subscription_id("示例订阅"),
                    "label": "示例订阅",
                    "url": "https://example.com/subscription",
                }
            ],
        }
        output = io.StringIO()

        with redirect_stdout(output):
            manager.command_list(state, names_only=True)

        self.assertEqual(output.getvalue().splitlines(), ["默认代理", "示例订阅"])

    def test_state_rejects_invalid_existing_group_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                '{"version": 1, "subscriptions": [], '
                '"include_existing_group": "false"}',
                encoding="utf-8",
            )
            with (
                mock.patch.object(manager, "STATE", state_path),
                self.assertRaisesRegex(manager.ManagerError, "默认入口状态无效"),
            ):
                manager.load_state("")

    def test_remove_existing_group_keeps_original_config(self) -> None:
        state = {
            "version": 1,
            "existing_group": "默认代理",
            "subscriptions": [
                {
                    "id": manager.subscription_id("示例订阅"),
                    "label": "示例订阅",
                    "url": "https://example.com/subscription",
                }
            ],
        }
        backup = Path("/tmp/config.backup")

        with (
            mock.patch.object(manager, "apply_change", return_value=backup) as apply,
            redirect_stdout(io.StringIO()),
        ):
            manager.command_remove("默认代理", "original", state, None)

        self.assertFalse(state["include_existing_group"])
        apply.assert_called_once_with("original", None, state)

    def test_remove_allows_last_existing_group(self) -> None:
        state = {
            "version": 1,
            "existing_group": "默认代理",
            "subscriptions": [],
        }
        backup = Path("/tmp/config.backup")

        with (
            mock.patch.object(manager, "apply_change", return_value=backup),
            redirect_stdout(io.StringIO()),
        ):
            manager.command_remove("默认代理", "original", state, None)

        self.assertFalse(state["include_existing_group"])

    def test_remove_last_subscription_keeps_existing_group_removed(self) -> None:
        label = "示例订阅"
        state = {
            "version": 1,
            "existing_group": "默认代理",
            "include_existing_group": False,
            "subscriptions": [
                {
                    "id": manager.subscription_id(label),
                    "label": label,
                    "url": "https://example.com/subscription",
                }
            ],
        }
        backup = Path("/tmp/config.backup")

        with (
            mock.patch.object(manager, "apply_change", return_value=backup),
            mock.patch.object(Path, "unlink"),
            redirect_stdout(io.StringIO()),
        ):
            manager.command_remove(label, "original", state, None)

        self.assertEqual(state["subscriptions"], [])
        self.assertFalse(state["include_existing_group"])

    def test_rewrite_rule_targets_preserves_trailing_modifiers(self) -> None:
        original = """rules:
  - MATCH,默认代理
  - IP-CIDR,203.0.113.0/24,默认代理,no-resolve
  - IP-CIDR6,2001:db8::/32,DIRECT,no-resolve
"""

        rendered, changed = manager.rewrite_rule_targets(
            original, "默认代理", "代理选择"
        )
        rules = yaml.safe_load(rendered)["rules"]

        self.assertEqual(changed, 2)
        self.assertEqual(rules[0], "MATCH,代理选择")
        self.assertEqual(
            rules[1], "IP-CIDR,203.0.113.0/24,代理选择,no-resolve"
        )
        self.assertEqual(rules[2], "IP-CIDR6,2001:db8::/32,DIRECT,no-resolve")

    def test_config_runs_mihomo_as_service_user(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = base / "config.yaml"
            runuser = base / "runuser"
            config.write_text("mode: rule\n", encoding="utf-8")
            runuser.write_text("", encoding="utf-8")
            account = SimpleNamespace(pw_uid=123, pw_gid=456)
            result = SimpleNamespace(returncode=0, stdout="")

            with (
                mock.patch.object(manager, "CONFIG", config),
                mock.patch.object(manager, "RUNUSER", runuser),
                mock.patch.object(manager, "MIHOMO", Path("/usr/local/bin/mihomo")),
                mock.patch.object(manager, "SERVICE_USER", "mihomo-test"),
                mock.patch.object(manager.pwd, "getpwnam", return_value=account),
                mock.patch.object(manager.os, "chown") as chown,
                mock.patch.object(manager.os, "chmod") as chmod,
                mock.patch.object(manager.subprocess, "run", return_value=result) as run,
            ):
                manager.test_config("mode: rule\n", [])

            command = run.call_args.args[0]
            self.assertEqual(
                command[:4], [str(runuser), "--user", "mihomo-test", "--"]
            )
            self.assertEqual(
                command[4:8], ["/usr/local/bin/mihomo", "-t", "-d", str(base)]
            )
            self.assertEqual(command[8], "-f")
            chown.assert_called_once()
            self.assertEqual(chown.call_args.args[1:], (123, 456))
            chmod.assert_called_once()
            self.assertEqual(chmod.call_args.args[1], 0o600)
            self.assertFalse(Path(chown.call_args.args[0]).exists())

    def test_label_is_stable_and_rejects_control_characters(self) -> None:
        self.assertEqual(
            manager.subscription_id("示例"), manager.subscription_id("示例")
        )
        with self.assertRaises(manager.ManagerError):
            manager.validate_label("bad\nlabel")


if __name__ == "__main__":
    unittest.main()
