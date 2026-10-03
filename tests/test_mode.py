from contextlib import redirect_stdout
import copy
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LOADER = SourceFileLoader("mihomo_mode", str(ROOT / "bin/mihomo-mode"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
mode = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mode)


def proxy_fixture():
    return {
        "GLOBAL": {"type": "Selector", "now": "DIRECT", "all": ["DIRECT", "代理选择"]},
        "代理选择": {"type": "Selector", "now": "订阅 A", "all": ["订阅 A", "订阅 B", "DIRECT"]},
        "订阅 A": {"type": "Selector", "now": "节点 A1", "all": ["节点 A1", "节点 A2"]},
        "订阅 B": {"type": "Selector", "now": "节点 B1", "all": ["节点 B1", "节点 B2"]},
        **{name: {"type": "Shadowsocks"} for name in ("节点 A1", "节点 A2", "节点 B1", "节点 B2")},
        "DIRECT": {"type": "Direct"},
    }


class FakeController(mode.Controller):
    def __init__(self):
        super().__init__("http://controller.invalid", "代理选择", "默认代理")
        self.config = {"mode": "rule"}
        self.groups = proxy_fixture()
        self.writes = []
        self.fail_after_mode_write = False
        self.ignore_global_write = False
        self.ignore_mode_write = False
        self.reject_modes = False

    def request(self, method, path, payload=None):
        if method == "GET":
            if path == "/configs":
                return self.config.copy()
            if path == "/proxies":
                return {"proxies": copy.deepcopy(self.groups)}
        self.writes.append((method, path, payload))
        if method == "PUT" and path == "/proxies/GLOBAL":
            if self.ignore_global_write:
                self.ignore_global_write = False
            else:
                self.groups["GLOBAL"]["now"] = payload["name"]
            return {}
        if method == "PATCH" and path == "/configs":
            if self.reject_modes:
                raise mode.ModeError("mode update rejected")
            if self.ignore_mode_write:
                self.ignore_mode_write = False
            else:
                self.config.update(payload)
            if self.fail_after_mode_write:
                self.fail_after_mode_write = False
                raise mode.ModeError("response lost after mode update")
            return {}
        raise AssertionError((method, path, payload))


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()

    def test_global_links_entry_before_mode_change_and_preserves_selected_node(self):
        original_entry = copy.deepcopy(self.controller.groups["代理选择"])
        self.controller.change("global")
        self.assertEqual(self.controller.config["mode"], "global")
        self.assertEqual(self.controller.groups["GLOBAL"]["now"], "代理选择")
        self.assertEqual(self.controller.groups["代理选择"], original_entry)
        self.assertEqual(self.controller.writes, [
            ("PUT", "/proxies/GLOBAL", {"name": "代理选择"}),
            ("PATCH", "/configs", {"mode": "global"}),
        ])
        self.assertEqual(self.controller.selection_path(self.controller.groups, "GLOBAL")[-1], "节点 A1")

    def test_global_automatically_follows_later_subscription_and_node_changes(self):
        self.controller.change("global")
        self.controller.groups["代理选择"]["now"] = "订阅 B"
        self.controller.groups["订阅 B"]["now"] = "节点 B2"
        output = io.StringIO()
        writes = self.controller.writes.copy()
        with redirect_stdout(output):
            self.controller.status()
        self.assertIn("GLOBAL → 代理选择 → 订阅 B → 节点 B2", output.getvalue())
        self.assertEqual(self.controller.writes, writes)

    def test_provider_node_missing_from_top_level_proxy_list_is_resolved(self):
        for name in ("节点 A1", "节点 A2", "节点 B1", "节点 B2"):
            self.controller.groups.pop(name)
        self.controller.change("global")
        self.assertEqual(self.controller.selection_path(self.controller.groups, "GLOBAL"),
                         ["GLOBAL", "代理选择", "订阅 A", "节点 A1"])
        output = io.StringIO()
        with redirect_stdout(output):
            self.controller.status()
        self.assertIn("节点 A1", output.getvalue())

    def test_unknown_selection_outside_group_choices_is_rejected(self):
        self.controller.groups["订阅 A"]["now"] = "不存在的节点"
        with self.assertRaisesRegex(mode.ModeError, "当前出口不在可选列表"):
            self.controller.change("global")
        self.assertEqual(self.controller.writes, [])

    def test_sync_global_leaves_mode_unchanged(self):
        self.controller.change()
        self.assertEqual(self.controller.config["mode"], "rule")
        self.assertFalse(any(method == "PATCH" for method, _, _ in self.controller.writes))

    def test_global_falls_back_to_same_base_group_as_selector(self):
        self.controller.groups["默认代理"] = self.controller.groups.pop("代理选择")
        self.controller.groups["GLOBAL"]["all"] = ["DIRECT", "默认代理"]
        self.controller.change("global")
        self.assertEqual(self.controller.groups["GLOBAL"]["now"], "默认代理")

    def test_rule_and_direct_do_not_change_node_selection(self):
        self.controller.config["mode"] = "global"
        original = copy.deepcopy(self.controller.groups)
        for target in ("rule", "direct"):
            self.controller.change(target)
            self.assertEqual(self.controller.config["mode"], target)
            self.assertEqual(self.controller.groups, original)

    def test_explicit_direct_selection_is_respected(self):
        self.controller.groups["代理选择"]["now"] = "DIRECT"
        self.controller.change("global")
        self.assertEqual(self.controller.selection_path(self.controller.groups, "GLOBAL"),
                         ["GLOBAL", "代理选择", "DIRECT"])

    def test_global_rejects_unavailable_entry_before_any_write(self):
        self.controller.groups["GLOBAL"]["all"] = ["DIRECT"]
        with self.assertRaisesRegex(mode.ModeError, "GLOBAL 无法选择入口"):
            self.controller.change("global")
        self.assertEqual(self.controller.writes, [])
        self.assertEqual(self.controller.config["mode"], "rule")

    def test_global_prevents_selector_cycle(self):
        self.controller.groups["订阅 A"]["now"] = "GLOBAL"
        with self.assertRaisesRegex(mode.ModeError, "循环关联"):
            self.controller.change("global")
        self.assertEqual(self.controller.writes, [])

    def test_failed_global_verification_never_enables_global_mode(self):
        self.controller.ignore_global_write = True
        with self.assertRaisesRegex(mode.ModeError, "已恢复原状态"):
            self.controller.change("global")
        self.assertEqual(self.controller.config["mode"], "rule")
        self.assertFalse(any(method == "PATCH" for method, _, _ in self.controller.writes))

    def test_lost_mode_response_restores_mode_before_global_outlet(self):
        self.controller.fail_after_mode_write = True
        with self.assertRaisesRegex(mode.ModeError, "已恢复原状态"):
            self.controller.change("global")
        self.assertEqual(self.controller.config["mode"], "rule")
        self.assertEqual(self.controller.groups["GLOBAL"]["now"], "DIRECT")
        self.assertEqual(self.controller.writes[-2:], [
            ("PATCH", "/configs", {"mode": "rule"}),
            ("PUT", "/proxies/GLOBAL", {"name": "DIRECT"}),
        ])

    def test_ignored_mode_update_does_not_report_success(self):
        self.controller.ignore_mode_write = True
        with self.assertRaisesRegex(mode.ModeError, "路由模式切换未生效"):
            self.controller.change("global")
        self.assertEqual(self.controller.config["mode"], "rule")
        self.assertEqual(self.controller.groups["GLOBAL"]["now"], "DIRECT")

    def test_rollback_failure_is_reported(self):
        self.controller.reject_modes = True
        with self.assertRaisesRegex(mode.ModeError, "恢复失败：路由模式"):
            self.controller.change("global")
        self.assertEqual(self.controller.groups["GLOBAL"]["now"], "DIRECT")

    def test_invalid_mode_has_no_controller_access(self):
        with (mock.patch.object(mode.sys, "argv", ["mihomo-mode", "invalid"]),
              mock.patch.object(mode, "Controller") as controller,
              mock.patch("sys.stderr", new=io.StringIO())):
            self.assertEqual(mode.main(), 2)
            controller.assert_not_called()


class SelectorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.state = self.directory / "state.json"
        self.state.write_text(json.dumps({"proxies": proxy_fixture(), "events": []}))
        scripts = {
            "systemctl": "#!/bin/sh\nexit 0\n",
            "curl": '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
from urllib.parse import unquote
p = Path(os.environ['SELECTOR_TEST_STATE'])
state = json.loads(p.read_text())
args = sys.argv[1:]
assert '--noproxy' in args and args[args.index('--noproxy') + 1] == '*'
url = next(value for value in args if value.startswith('http://'))
name = unquote(url.rsplit('/', 1)[-1])
if '-X' in args:
    payload = json.loads(args[args.index('-d') + 1])
    state['proxies'][name]['now'] = payload['name']
    state['events'].append(['select', name, payload['name']])
    p.write_text(json.dumps(state))
elif name not in state['proxies']:
    sys.exit(22)
else:
    print(json.dumps(state['proxies'][name]))
''',
            "mode-helper": '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
assert sys.argv[1:] == ['--sync-global']
p = Path(os.environ['SELECTOR_TEST_STATE'])
state = json.loads(p.read_text())
entry = os.environ['MIHOMO_ENTRY_GROUP']
state['events'].append(['sync', entry])
if os.environ.get('SELECTOR_TEST_SYNC_FAIL'):
    p.write_text(json.dumps(state))
    sys.exit(1)
state['proxies']['GLOBAL']['now'] = entry
p.write_text(json.dumps(state))
''',
        }
        for name, content in scripts.items():
            path = self.directory / name
            path.write_text(content)
            path.chmod(0o755)
        self.environment = {**os.environ, "PATH": str(self.directory) + os.pathsep + os.environ["PATH"],
                            "MIHOMO_API": "http://controller.invalid", "MIHOMO_ENTRY_GROUP": "代理选择",
                            "MIHOMO_BASE_GROUP": "默认代理", "MIHOMO_MODE": str(self.directory / "mode-helper"),
                            "SELECTOR_TEST_STATE": str(self.state)}

    def select(self, choices):
        return subprocess.run(["bash", str(ROOT / "bin/mihomo-select")], input=choices,
                              env=self.environment, text=True, capture_output=True, timeout=10)

    def test_subscription_and_node_selection_link_global_before_changing_node(self):
        result = self.select("2\n2\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.state.read_text())
        self.assertEqual(state["events"], [["sync", "代理选择"],
                                          ["select", "代理选择", "订阅 B"],
                                          ["select", "订阅 B", "节点 B2"]])
        self.assertEqual(mode.Controller.selection_path(state["proxies"], "GLOBAL")[-1], "节点 B2")
        self.assertIn("GLOBAL 同步跟随", result.stdout)

    def test_direct_choice_also_synchronizes_global(self):
        result = self.select("3\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.state.read_text())
        self.assertEqual(mode.Controller.selection_path(state["proxies"], "GLOBAL")[-1], "DIRECT")

    def test_failed_sync_keeps_previous_selection(self):
        self.environment["SELECTOR_TEST_SYNC_FAIL"] = "1"
        result = self.select("2\n2\n")
        self.assertNotEqual(result.returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertEqual(state["events"], [["sync", "代理选择"]])
        self.assertEqual(state["proxies"]["代理选择"]["now"], "订阅 A")

    def test_cancel_before_selection_has_no_side_effects(self):
        result = self.select("")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(self.state.read_text())["events"], [])


if __name__ == "__main__":
    unittest.main()
