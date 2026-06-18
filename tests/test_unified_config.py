import json
import tempfile
import unittest
from pathlib import Path

from lib.local_config import (
    DEFAULT_CONFIG,
    export_safe_config,
    legacy_settings_to_config,
    load_config,
    merge_config_sources,
    migrate_config_file,
    migrate_legacy_config,
    reset_config,
    save_config,
    update_config,
    validate_config,
)


class UnifiedConfigTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def valid_payload(self):
        return {
            "version": 1,
            "user": {
                "category": "  运动鞋  ",
                "keywords": ["运动鞋", "运动鞋", "", " 凉鞋 "],
                "target_count": "12",
                "candidate_limit": "48",
                "purchase_price_min": "10.5",
                "purchase_price_max": "99",
                "max_weight_kg": "1.8",
                "minimum_profit_margin": "0.25",
                "auto_season_check": "true",
                "image_strategy": "inspect_and_fix",
                "run_mode": "simulation",
            },
            "advanced": {
                "search_max_pages": "2",
                "page_load_timeout_seconds": "30",
                "step_retry_count": "2",
                "task_failure_limit": "10",
                "collection_interval_seconds": "3",
                "prefer_plugin": True,
                "enable_link_fallback": True,
                "browser_path": "",
                "browser_user_data_dir": "data/chrome-profile",
                "cdp_port": "9222",
                "alibaba_url": "https://www.1688.com/",
                "miaoshou_url": "https://erp.91miaoshou.com/",
                "plugin_id": "",
                "database_path": "data/workbench.db",
                "log_path": "data/logs",
                "image_inspection_enabled": True,
                "image_min_width": "600",
                "image_min_height": "600",
                "image_service_url": "",
                "image_service_timeout_seconds": "30",
                "dedup_scope": "all",
                "no_publish": True,
                "collect_to_box_only": True,
                "safety_checks_enabled": True,
                "enable_dedupe": True,
                "enable_risk_filter": True,
                "enable_title_clean": True,
                "enable_image_check": True,
                "enable_miaoshou_collect": True,
                "per_run_item_limit": 10,
                "per_keyword_page_limit": 2,
            },
        }

    def test_default_config_is_valid_and_safe(self):
        result = validate_config(DEFAULT_CONFIG)

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["normalized_config"]["version"], 1)
        self.assertEqual(result["normalized_config"]["user"]["run_mode"], "simulation")
        self.assertTrue(result["normalized_config"]["advanced"]["no_publish"])
        self.assertTrue(result["normalized_config"]["advanced"]["collect_to_box_only"])

    def test_missing_config_file_loads_default(self):
        config = load_config(self.root)

        self.assertEqual(config["version"], 1)
        self.assertEqual(config["user"]["run_mode"], "simulation")
        self.assertTrue((self.root / "config.json").exists())

    def test_damaged_json_is_backed_up_and_safe_default_is_returned(self):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "config.json").write_text("{broken", encoding="utf-8")

        config = load_config(self.root)
        backups = list(self.root.glob("config.json.invalid.*.bak"))

        self.assertTrue(backups)
        self.assertTrue(config["no_publish"])
        self.assertTrue(config["_configWarnings"])

    def test_valid_user_config_is_normalized(self):
        result = validate_config(self.valid_payload())

        self.assertTrue(result["valid"], result["errors"])
        user = result["normalized_config"]["user"]
        self.assertEqual(user["category"], "运动鞋")
        self.assertEqual(user["keywords"], ["运动鞋", "凉鞋"])
        self.assertEqual(user["target_count"], 12)
        self.assertEqual(user["candidate_limit"], 48)
        self.assertEqual(user["purchase_price_min"], 10.5)
        self.assertEqual(user["minimum_profit_margin"], 0.25)
        self.assertTrue(user["auto_season_check"])

    def test_empty_keywords_are_rejected(self):
        payload = self.valid_payload()
        payload["user"]["keywords"] = ["", "   "]

        result = validate_config(payload)

        self.assertFalse(result["valid"])
        self.assertIn("user.keywords", [item["field"] for item in result["errors"]])

    def test_price_range_error_is_reported(self):
        payload = self.valid_payload()
        payload["user"]["purchase_price_min"] = 100
        payload["user"]["purchase_price_max"] = 10

        result = validate_config(payload)

        self.assertFalse(result["valid"])
        self.assertIn("user.purchase_price_min", [item["field"] for item in result["errors"]])

    def test_candidate_limit_must_not_be_smaller_than_target(self):
        payload = self.valid_payload()
        payload["user"]["target_count"] = 20
        payload["user"]["candidate_limit"] = 10

        result = validate_config(payload)

        self.assertFalse(result["valid"])
        self.assertIn("user.candidate_limit", [item["field"] for item in result["errors"]])

    def test_weight_and_profit_margin_validation(self):
        payload = self.valid_payload()
        payload["user"]["max_weight_kg"] = 0
        payload["user"]["minimum_profit_margin"] = 25

        result = validate_config(payload)
        fields = [item["field"] for item in result["errors"]]

        self.assertFalse(result["valid"])
        self.assertIn("user.max_weight_kg", fields)
        self.assertIn("user.minimum_profit_margin", fields)

    def test_invalid_enums_are_reported(self):
        payload = self.valid_payload()
        payload["user"]["image_strategy"] = "fake"
        payload["advanced"]["dedup_scope"] = "global"

        result = validate_config(payload)
        fields = [item["field"] for item in result["errors"]]

        self.assertFalse(result["valid"])
        self.assertIn("user.image_strategy", fields)
        self.assertIn("advanced.dedup_scope", fields)

    def test_publish_mode_is_rejected(self):
        payload = self.valid_payload()
        payload["user"]["run_mode"] = "publish"

        result = validate_config(payload)

        self.assertFalse(result["valid"])
        self.assertIn("user.run_mode", [item["field"] for item in result["errors"]])

    def test_advanced_port_and_url_are_validated(self):
        payload = self.valid_payload()
        payload["advanced"]["cdp_port"] = 70000
        payload["advanced"]["alibaba_url"] = "ftp://1688.example"

        result = validate_config(payload)
        fields = [item["field"] for item in result["errors"]]

        self.assertFalse(result["valid"])
        self.assertIn("advanced.cdp_port", fields)
        self.assertIn("advanced.alibaba_url", fields)

    def test_unknown_fields_are_warned_and_preserved_in_legacy(self):
        payload = self.valid_payload()
        payload["user"]["unexpected"] = "keep me"
        payload["advanced"]["selector_recipe"] = [{"type": "click"}]

        result = validate_config(payload)

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["warnings"])
        self.assertEqual(result["normalized_config"]["legacy"]["user"]["unexpected"], "keep me")
        self.assertEqual(result["normalized_config"]["legacy"]["advanced"]["selector_recipe"], [{"type": "click"}])

    def test_safe_write_creates_backup_and_stores_structured_config(self):
        first = save_config(self.root, self.valid_payload())
        second_payload = self.valid_payload()
        second_payload["user"]["category"] = "凉鞋"
        second = save_config(self.root, second_payload)
        saved = json.loads((self.root / "config.json").read_text(encoding="utf-8"))
        backups = list(self.root.glob("config.json.bak"))

        self.assertEqual(first["user"]["category"], "运动鞋")
        self.assertEqual(second["user"]["category"], "凉鞋")
        self.assertEqual(saved["user"]["category"], "凉鞋")
        self.assertTrue(backups)

    def test_invalid_save_does_not_overwrite_existing_config(self):
        save_config(self.root, self.valid_payload())
        before = (self.root / "config.json").read_text(encoding="utf-8")
        bad = self.valid_payload()
        bad["user"]["run_mode"] = "publish"

        with self.assertRaisesRegex(ValueError, "user.run_mode"):
            save_config(self.root, bad)

        self.assertEqual((self.root / "config.json").read_text(encoding="utf-8"), before)

    def test_system_input_is_not_saved_by_normal_save(self):
        payload = self.valid_payload()
        payload["system"] = {
            "platform": "Injected",
            "python_version": "0.0.0",
            "chrome_detected": True,
            "last_environment_check_at": "2099-01-01",
        }

        config = save_config(self.root, payload)
        saved = json.loads((self.root / "config.json").read_text(encoding="utf-8"))

        self.assertNotEqual(config["system"]["platform"], "Injected")
        self.assertNotEqual(saved["system"]["python_version"], "0.0.0")
        self.assertTrue(config["_configWarnings"])

    def test_legacy_flat_config_is_migrated_with_weight_kg_and_safe_mode(self):
        legacy = {
            "mode": "publish",
            "dry_run_collect": False,
            "collect_to_box_only": False,
            "no_publish": False,
            "keywords": ["鞋", "鞋", ""],
            "max_items_per_run": 9,
            "max_pages_per_keyword": 2,
            "max_retry": 2,
            "max_weight_g": 1500,
            "chrome_profile_dir": "data/chrome-profile",
            "chrome_debug_port": 9333,
        }

        config = load_config(self.root)
        result = validate_config({**legacy, **config.get("legacy", {})})
        report = migrate_legacy_config(legacy)
        migrated = validate_config(legacy)["normalized_config"]

        self.assertTrue(config["no_publish"])
        self.assertEqual(result["normalized_config"]["advanced"]["browser_user_data_dir"], "data/chrome-profile")
        self.assertTrue(report["migrated"])
        self.assertEqual(report["source_version"], 0)
        self.assertEqual(report["target_version"], 1)
        self.assertIn("user.max_weight_kg", report["changed_fields"])
        self.assertEqual(migrated["user"]["run_mode"], "collect_to_box")
        self.assertEqual(migrated["user"]["max_weight_kg"], 1.5)
        self.assertTrue(migrated["advanced"]["no_publish"])

    def test_structured_config_with_legacy_aliases_keeps_safety_boundary(self):
        payload = self.valid_payload()
        payload["no_publish"] = False
        payload["collect_to_box_only"] = False
        payload["mode"] = "publish"

        config = save_config(self.root, payload)

        self.assertTrue(config["no_publish"])
        self.assertTrue(config["collect_to_box_only"])
        self.assertNotEqual(config["user"]["run_mode"], "publish")

    def test_reset_and_export_safe_config(self):
        save_config(self.root, self.valid_payload())
        reset = reset_config(self.root)
        safe = export_safe_config(reset)

        self.assertEqual(reset["user"]["run_mode"], "simulation")
        self.assertEqual(safe["advanced"]["browser_user_data_dir"], "<local-path>")
        self.assertNotIn("legacy", safe)

    def test_legacy_settings_can_seed_new_config(self):
        report = legacy_settings_to_config({
            "automation.cdp_port": 9333,
            "automation.alibaba_url": "https://www.1688.com/",
            "automation.miaoshou_url": "https://erp.91miaoshou.com/",
            "automation.plugin_extension_id": "plugin-id",
            "image.base_url": "https://image.example",
            "market.target_margin_pct": 25,
            "evaluation.threshold": 70,
        })

        self.assertTrue(report["migrated"])
        config = validate_config(report["normalized_config"])["normalized_config"]
        self.assertEqual(config["advanced"]["cdp_port"], 9333)
        self.assertEqual(config["advanced"]["plugin_id"], "plugin-id")
        self.assertEqual(config["advanced"]["image_service_url"], "https://image.example")
        self.assertEqual(config["user"]["minimum_profit_margin"], 0.25)
        self.assertIn("evaluation.threshold", report["ignored_fields"])

    def test_new_config_takes_priority_over_legacy_settings(self):
        new_config = self.valid_payload()
        new_config["advanced"]["cdp_port"] = 9444
        result = merge_config_sources(
            new_config=new_config,
            settings={"automation.cdp_port": 9333, "market.target_margin_pct": 30},
        )

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["normalized_config"]["advanced"]["cdp_port"], 9444)
        self.assertEqual(result["normalized_config"]["user"]["minimum_profit_margin"], 0.25)

    def test_migration_backs_up_legacy_file_and_is_idempotent(self):
        self.root.mkdir(parents=True, exist_ok=True)
        legacy = {
            "mode": "real",
            "dry_run_collect": True,
            "keywords": ["鞋"],
            "max_weight_g": 1200,
        }
        (self.root / "config.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

        first = migrate_config_file(self.root, settings={"automation.cdp_port": 9333})
        second = migrate_config_file(self.root, settings={"automation.cdp_port": 9444})

        self.assertTrue(first["migrated"])
        self.assertTrue(first["backup_path"])
        self.assertTrue(Path(first["backup_path"]).exists())
        self.assertFalse(second["migrated"])
        self.assertEqual(load_config(self.root)["chrome_debug_port"], 9333)

    def test_damaged_legacy_config_migration_uses_settings_without_crashing(self):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "config.json").write_text("{broken", encoding="utf-8")

        result = migrate_config_file(self.root, settings={"automation.cdp_port": 9555})

        self.assertTrue(result["migrated"])
        self.assertEqual(load_config(self.root)["chrome_debug_port"], 9555)
        self.assertTrue(list(self.root.glob("config.json.invalid.*.bak")))

    def test_missing_config_can_be_seeded_from_settings_once(self):
        first = migrate_config_file(self.root, settings={
            "automation.cdp_port": 9555,
            "automation.alibaba_url": "https://www.1688.com/",
            "automation.miaoshou_url": "https://erp.91miaoshou.com/",
        })
        second = migrate_config_file(self.root, settings={"automation.cdp_port": 9666})

        self.assertTrue(first["migrated"])
        self.assertEqual(first["source_version"], "settings")
        self.assertIn("advanced.cdp_port", first["changed_fields"])
        self.assertEqual(load_config(self.root)["chrome_debug_port"], 9555)
        self.assertFalse(second["migrated"])
        self.assertEqual(load_config(self.root)["chrome_debug_port"], 9555)

    def test_partial_user_update_preserves_other_fields_and_ignores_system(self):
        save_config(self.root, self.valid_payload())
        updated = update_config(self.root, {"category": "雨鞋", "system": {"platform": "bad"}}, "user")

        self.assertEqual(updated["user"]["category"], "雨鞋")
        self.assertEqual(updated["user"]["keywords"], ["运动鞋", "凉鞋"])
        self.assertNotEqual(updated["system"]["platform"], "bad")
        self.assertTrue(updated["_configWarnings"])

    def test_export_safe_config_redacts_sensitive_unknown_fields(self):
        payload = self.valid_payload()
        payload["advanced"]["api_key"] = "secret"

        result = validate_config(payload)
        safe = export_safe_config(result["normalized_config"])

        self.assertNotIn("secret", json.dumps(safe, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
