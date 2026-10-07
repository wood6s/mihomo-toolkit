from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import json
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
    def mixed_config(self, provider_section=None):
        if provider_section is None:
            provider_section = """proxy-providers:
  # Existing subscription, maintained outside this tool.
  original: &original_provider
    type: file
    path: ./existing.yaml
    health-check: {enable: false}
  managed_sub_foreign:
    <<: *original_provider
    path: ./other.yaml
"""
        return provider_section + """proxy-groups:
  - {name: 默认代理, type: select, use: [original, managed_sub_foreign]}
rules:
  - MATCH,默认代理
"""

    def new_state(self, label="新增订阅"):
        return {"version": 1, "target_group": "", "subscriptions": [
            {"id": manager.subscription_id(label), "label": label,
             "url": "https://example.com/new-subscription"}]}

    def assert_external_preserved(self, original, rendered):
        external = manager.load_yaml(original).get("proxy-providers") or {}
        actual = manager.load_yaml(rendered).get("proxy-providers") or {}
        self.assertEqual({name: actual[name] for name in external}, external)

    def test_external_providers_and_prefixed_use_survive_add_and_remove(self):
        original = self.mixed_config()
        state = self.new_state()
        added = manager.render_config(original, state)
        self.assert_external_preserved(original, added)
        self.assertIn("# Existing subscription, maintained outside this tool.", added)
        self.assertIn("original: &original_provider", added)
        group = next(g for g in manager.load_yaml(added)["proxy-groups"] if g["name"] == "默认代理")
        self.assertEqual(group["use"], ["original", "managed_sub_foreign"])
        state["subscriptions"] = []
        removed = manager.render_config(added, state)
        self.assert_external_preserved(original, removed)
        self.assertNotIn(manager.BEGIN_PROVIDERS, removed)
        self.assertEqual(set(manager.load_yaml(removed)["proxy-providers"]),
                         {"original", "managed_sub_foreign"})

    def test_repeated_add_remove_and_rerender_are_stable(self):
        original = self.mixed_config()
        state = self.new_state()
        first = manager.render_config(original, state)
        self.assertEqual(manager.render_config(first, state), first)
        state["subscriptions"].extend(self.new_state("第二订阅")["subscriptions"])
        second = manager.render_config(first, state)
        self.assert_external_preserved(original, second)
        self.assertEqual(second.count(manager.BEGIN_PROVIDERS), 1)
        self.assertEqual(second.count("proxy-providers:"), 1)
        state["subscriptions"].pop(0)
        removed = manager.render_config(second, state)
        providers = manager.load_yaml(removed)["proxy-providers"]
        self.assertNotIn(manager.subscription_id("新增订阅"), providers)
        self.assertIn(manager.subscription_id("第二订阅"), providers)
        self.assert_external_preserved(original, removed)

    def test_flow_providers_preserve_original_text_and_allow_remove(self):
        provider = 'proxy-providers: {original: {type: file, path: ./existing.yaml}, managed_sub_foreign: {type: file, path: ./other.yaml}} # keep\n'
        original = self.mixed_config(provider)
        state = self.new_state()
        added = manager.render_config(original, state)
        self.assert_external_preserved(original, added)
        self.assertIn(provider.split("{", 1)[1], added)
        self.assertEqual(manager.render_config(added, state), added)
        state["subscriptions"] = []
        removed = manager.render_config(added, state)
        self.assert_external_preserved(original, removed)
        self.assertNotIn(manager.BEGIN_PROVIDERS, removed)

    def test_empty_provider_section_and_arbitrary_indentation(self):
        for section in ("proxy-providers: {}\n", "proxy-providers: # empty\n",
                        "proxy-providers: null # empty\n", "proxy-providers: ~\n",
                        "'proxy-providers':\n    original: {type: file, path: ./existing.yaml}\n"):
            with self.subTest(section=section):
                original = self.mixed_config(section)
                state = self.new_state()
                added = manager.render_config(original, state)
                self.assert_external_preserved(original, added)
                self.assertIn(state["subscriptions"][0]["id"], manager.load_yaml(added)["proxy-providers"])
                self.assertEqual(manager.render_config(added, state), added)
                state["subscriptions"] = []
                removed = manager.render_config(added, state)
                self.assertEqual(manager.load_yaml(removed).get("proxy-providers") or {},
                                 manager.load_yaml(original).get("proxy-providers") or {})

    def test_provider_mapping_at_end_of_document(self):
        original = self.mixed_config("") + "proxy-providers:\n  original: {type: file, path: ./existing.yaml}"
        state = self.new_state()
        added = manager.render_config(original, state)
        self.assert_external_preserved(original, added)
        self.assertEqual(manager.render_config(added, state), added)

    def test_legacy_top_level_managed_block_migrates_without_loss(self):
        original = self.mixed_config("").replace("use: [original, managed_sub_foreign]", "proxies: [DIRECT]")
        state = self.new_state()
        added = manager.render_config(original, state)
        self.assertIn(manager.BEGIN_PROVIDERS + "\nproxy-providers:\n", added)
        self.assertEqual(manager.render_config(added, state), added)
        state["subscriptions"] = []
        removed = manager.render_config(added, state)
        self.assertNotIn("proxy-providers", manager.load_yaml(removed))

    def test_collision_with_external_provider_is_rejected(self):
        state = self.new_state()
        provider_id = state["subscriptions"][0]["id"]
        original = self.mixed_config(f"proxy-providers:\n  {provider_id}: {{type: file, path: ./original.yaml}}\n")
        with self.assertRaisesRegex(manager.ManagerError, "provider 名称.*冲突"):
            manager.render_config(original, state)

    def test_collision_with_external_cache_path_is_rejected(self):
        state = self.new_state()
        provider_id = state["subscriptions"][0]["id"]
        for path in (f"./proxy_providers/{provider_id}.yaml",
                     str(manager.CONFIG.parent / "proxy_providers" / f"{provider_id}.yaml"),
                     f"./elsewhere/../proxy_providers/{provider_id}.yaml"):
            with self.subTest(path=path):
                original = self.mixed_config(f"proxy-providers:\n  original: {{type: file, path: {path}}}\n")
                with self.assertRaisesRegex(manager.ManagerError, "缓存路径.*冲突"):
                    manager.render_config(original, state)

    def test_duplicate_yaml_keys_are_rejected_without_disclosing_values(self):
        for text in ("proxy-providers: {}\nproxy-providers: {}\n",
                     "proxy-providers:\n  same: {}\n  same: {}\n",
                     "proxy-providers:\n  one: {url: secret-one, url: secret-two}\n"):
            with self.subTest(text=text):
                with self.assertRaises(manager.ManagerError) as error:
                    manager.render_config(text, self.new_state())
                self.assertIn("重复", str(error.exception))
                self.assertNotIn("secret", str(error.exception))

    def test_yaml_merge_overrides_still_work(self):
        parsed = manager.load_yaml("defaults: &base {type: http, interval: 600}\nprovider: {<<: *base, interval: 3600}\n")
        self.assertEqual(parsed["provider"], {"type": "http", "interval": 3600})

    def test_remove_refuses_to_unlink_an_external_shared_cache(self):
        state = self.new_state()
        provider_id = state["subscriptions"][0]["id"]
        added = manager.render_config(self.mixed_config(), state)
        added = added.replace("./existing.yaml", f"./proxy_providers/{provider_id}.yaml")
        state["subscriptions"] = []
        with self.assertRaisesRegex(manager.ManagerError, "缓存路径.*冲突"):
            manager.render_config(added, state)

    def test_malformed_or_duplicate_managed_markers_are_rejected(self):
        for text in ("  " + manager.BEGIN_PROVIDERS + "\n",
                     "  " + manager.BEGIN_PROVIDERS + "\n" + manager.END_PROVIDERS + "\n",
                     manager.provider_block([]) + "\n" + manager.provider_block([]) + "\n"):
            with self.subTest(text=text), self.assertRaises(manager.ManagerError):
                manager.strip_provider_block(text)

    def test_external_provider_alias_is_refused_before_rewriting(self):
        original = self.mixed_config("external: &external {original: {type: file, path: ./existing.yaml}}\nproxy-providers: *external\n")
        with self.assertRaisesRegex(manager.ManagerError, "外部 YAML 别名"):
            manager.render_config(original, self.new_state())

    def test_add_failure_never_writes_config_or_state(self):
        state = self.new_state()
        provider_id = state["subscriptions"][0]["id"]
        original = self.mixed_config(f"proxy-providers:\n  {provider_id}: {{type: file, path: ./existing.yaml}}\n")
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(original)
            with (mock.patch.object(manager, "CONFIG", config),
                  mock.patch.object(manager, "write_atomic") as write,
                  mock.patch.object(manager, "test_config") as validate,
                  self.assertRaises(manager.ManagerError)):
                manager.apply_change(original, b'{"version": 1, "subscriptions": []}', copy.deepcopy(state))
            write.assert_not_called()
            validate.assert_not_called()
            self.assertEqual(config.read_text(), original)

    def markerless_config(self, block_style=False):
        original = self.mixed_config()
        state = self.new_state("旧订阅")
        rendered = manager.render_config(original, state)
        if block_style:
            rendered = yaml.safe_dump(manager.load_yaml(rendered), allow_unicode=True,
                                      sort_keys=False, default_flow_style=False)
        else:
            rendered = "\n".join(line for line in rendered.splitlines()
                                 if "MIHOMO MANAGED" not in line) + "\n"
        return rendered, state

    def test_recovery_from_comment_loss_and_yaml_reformatting_preserves_values(self):
        for block_style in (False, True):
            with self.subTest(block_style=block_style):
                original, state = self.markerless_config(block_style)
                before_state = copy.deepcopy(state)
                recovered = manager.recover_managed_markers(original, state)
                self.assertEqual(manager.load_yaml(original), manager.load_yaml(recovered))
                self.assertEqual(state, before_state)
                self.assertEqual(recovered.count(manager.BEGIN_PROVIDERS), 1)
                self.assertEqual(recovered.count(manager.BEGIN_GROUPS), 1)
                self.assertEqual(manager.recover_managed_markers(recovered, state), recovered)

    def test_add_after_recovery_preserves_old_and_external_subscriptions(self):
        original, previous = self.markerless_config(True)
        current = copy.deepcopy(previous)
        current["subscriptions"].extend(self.new_state("新订阅")["subscriptions"])
        rendered = manager.render_config(original, current, previous)
        self.assert_external_preserved(original, rendered)
        self.assertEqual(len(manager.load_yaml(rendered)["proxy-providers"]), 4)
        self.assertEqual(manager.render_config(rendered, current, current), rendered)

    def test_remove_after_recovery_removes_only_saved_managed_subscription(self):
        original, previous = self.markerless_config(True)
        current = copy.deepcopy(previous)
        current["subscriptions"] = []
        rendered = manager.render_config(original, current, previous)
        self.assertEqual(manager.load_yaml(rendered)["proxy-providers"],
                         manager.load_yaml(self.mixed_config())["proxy-providers"])
        names = [group["name"] for group in manager.load_yaml(rendered)["proxy-groups"]]
        self.assertNotIn("旧订阅", names)
        self.assertNotIn(manager.BEGIN_PROVIDERS, rendered)

    def test_recovery_handles_only_one_missing_marker_section(self):
        state = self.new_state("旧订阅")
        rendered = manager.render_config(self.mixed_config(), state)
        for start, end in ((manager.BEGIN_PROVIDERS, manager.END_PROVIDERS),
                           (manager.BEGIN_GROUPS, manager.END_GROUPS)):
            with self.subTest(start=start):
                unmarked = "\n".join(line for line in rendered.splitlines()
                                      if start not in line and end not in line) + "\n"
                recovered = manager.recover_managed_markers(unmarked, state)
                self.assertEqual(manager.load_yaml(recovered), manager.load_yaml(rendered))
                self.assertIn(manager.BEGIN_PROVIDERS, recovered)
                self.assertIn(manager.BEGIN_GROUPS, recovered)

    def test_recovery_requires_persisted_state_and_exact_provider_match(self):
        original, state = self.markerless_config(True)
        with self.assertRaisesRegex(manager.ManagerError, "provider 名称.*冲突"):
            manager.render_config(original, copy.deepcopy(state))
        provider_id = state["subscriptions"][0]["id"]
        for field, value in (("url", "https://example.com/changed"), ("path", "./other.yaml"),
                             ("interval", 123), ("custom-field", "new")):
            with self.subTest(field=field):
                parsed = manager.load_yaml(original)
                parsed["proxy-providers"][provider_id][field] = value
                modified = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
                with self.assertRaisesRegex(manager.ManagerError, "旧订阅源.*不完全匹配"):
                    manager.recover_managed_markers(modified, state)

    def test_recovery_rejects_missing_or_changed_groups(self):
        original, state = self.markerless_config(True)
        for name in ("旧订阅", "代理选择"):
            with self.subTest(name=name):
                parsed = manager.load_yaml(original)
                group = next(g for g in parsed["proxy-groups"] if g["name"] == name)
                group["proxies"] = ["DIRECT"]
                modified = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
                with self.assertRaisesRegex(manager.ManagerError, "旧订阅策略组.*不完全匹配"):
                    manager.recover_managed_markers(modified, state)

    def test_recovery_does_not_adopt_a_new_colliding_provider(self):
        original, previous = self.markerless_config(True)
        new_entry = self.new_state("新订阅")["subscriptions"][0]
        parsed = manager.load_yaml(original)
        parsed["proxy-providers"].update(manager.load_yaml(manager.provider_block([new_entry]))["proxy-providers"])
        original = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
        current = copy.deepcopy(previous)
        current["subscriptions"].append(new_entry)
        with self.assertRaisesRegex(manager.ManagerError, "provider 名称.*冲突"):
            manager.render_config(original, current, previous)

    def test_recovery_with_no_remaining_subscriptions(self):
        state = self.new_state()
        state["subscriptions"] = []
        state["include_existing_group"] = False
        marked = manager.render_config(self.mixed_config(), state)
        unmarked = yaml.safe_dump(manager.load_yaml(marked), allow_unicode=True, sort_keys=False)
        recovered = manager.recover_managed_markers(unmarked, state)
        self.assertEqual(manager.load_yaml(marked), manager.load_yaml(recovered))

    def test_recovery_validation_failure_never_writes_config_or_state(self):
        original, previous = self.markerless_config(True)
        current = copy.deepcopy(previous)
        current["subscriptions"].extend(self.new_state("新订阅")["subscriptions"])
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(original)
            with (mock.patch.object(manager, "CONFIG", config),
                  mock.patch.object(manager, "write_atomic") as write,
                  mock.patch.object(manager, "test_config", side_effect=manager.ManagerError("validation failed")),
                  mock.patch.object(manager, "backup_current") as backup,
                  self.assertRaisesRegex(manager.ManagerError, "validation failed")):
                manager.apply_change(original, json.dumps(previous).encode(), current)
            write.assert_not_called()
            backup.assert_not_called()
            self.assertEqual(config.read_text(), original)

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
