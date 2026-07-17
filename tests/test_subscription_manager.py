from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import unittest

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
        self.assertEqual(
            list(parsed["proxy-providers"]), [manager.subscription_id(label)]
        )
        self.assertIn("MATCH,代理选择", parsed["rules"])

        entry = next(
            group for group in parsed["proxy-groups"] if group["name"] == "代理选择"
        )
        self.assertEqual(entry["proxies"], ["默认代理", label])

    def test_label_is_stable_and_rejects_control_characters(self) -> None:
        self.assertEqual(
            manager.subscription_id("示例"), manager.subscription_id("示例")
        )
        with self.assertRaises(manager.ManagerError):
            manager.validate_label("bad\nlabel")


if __name__ == "__main__":
    unittest.main()
