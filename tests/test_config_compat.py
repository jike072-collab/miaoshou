import json
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import app
from lib.database import Database
from lib.local_config import ConfigValidationError, config_error_response, config_response, load_config, save_config, update_config


RUNTIME_SYSTEM = {
    "platform": "Darwin",
    "python_version": "3.11.9",
    "chrome_detected": True,
    "cdp_available": True,
    "alibaba_logged_in": True,
    "miaoshou_logged_in": True,
    "plugin_detected": True,
    "last_environment_check_at": "2026-06-18T10:00:00Z",
}


class ConfigCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.original_db = app.DB
        self.original_data_dir = app.DATA_DIR
        self.root = Path(tempfile.mkdtemp())
        app.DATA_DIR = self.root
        app.DB = Database(self.root / "test.db")

    def tearDown(self):
        app.DB = self.original_db
        app.DATA_DIR = self.original_data_dir

    def handler(self):
        handler = object.__new__(app.AppHandler)

        def send_json(payload, status=HTTPStatus.OK):
            return {"payload": payload, "status": status}

        handler.send_json = send_json
        return handler

    def test_apply_config_to_settings_syncs_compatible_fields(self):
        config = save_config(self.root, {
            "version": 1,
            "user": {"category": "鞋类", "keywords": ["鞋"], "run_mode": "simulation"},
            "advanced": {
                "browser_user_data_dir": "data/profile",
                "cdp_port": 9333,
                "alibaba_url": "https://www.1688.com/",
                "miaoshou_url": "https://erp.91miaoshou.com/",
                "no_publish": True,
                "collect_to_box_only": True,
            },
        })

        app.sync_settings_from_config(config)

        self.assertEqual(app.DB.setting("automation.cdp_port"), 9333)
        self.assertEqual(app.DB.setting("automation.chrome_profile_dir"), "data/profile")
        self.assertEqual(app.DB.setting("automation.alibaba_url"), "https://www.1688.com/")
        self.assertEqual(app.DB.setting("automation.mode"), "dry_run")

    def test_collect_to_box_syncs_legacy_mode_without_enabling_publish(self):
        config = save_config(self.root, {
            "version": 1,
            "user": {"category": "鞋类", "keywords": ["鞋"], "run_mode": "collect_to_box"},
            "advanced": {"no_publish": True, "collect_to_box_only": True},
        })

        app.sync_settings_from_config(config)

        self.assertEqual(app.DB.setting("automation.mode"), "live")
        self.assertTrue(load_config(self.root)["no_publish"])
        self.assertTrue(load_config(self.root)["collect_to_box_only"])

    def test_settings_sync_failure_does_not_break_config_file(self):
        config = save_config(self.root, {"keywords": ["鞋"], "max_items_per_run": 8})
        before = (self.root / "config.json").read_text(encoding="utf-8")

        with patch.object(app.DB, "set_settings", side_effect=RuntimeError("db locked")):
            with self.assertRaisesRegex(RuntimeError, "db locked"):
                app.sync_settings_from_config(config)

        self.assertEqual((self.root / "config.json").read_text(encoding="utf-8"), before)

    def test_config_response_does_not_expose_sensitive_legacy_values(self):
        config = load_config(self.root)
        config.setdefault("legacy", {}).setdefault("advanced", {})["api_key"] = "secret"

        response = config_response(config)

        self.assertTrue(response["ok"])
        self.assertNotIn("secret", json.dumps(response, ensure_ascii=False))

    def test_partial_update_does_not_delete_existing_keywords(self):
        save_config(self.root, {"keywords": ["运动鞋", "凉鞋"], "max_items_per_run": 8})
        updated = update_config(self.root, {"category": "鞋类"}, "user")

        self.assertEqual(updated["user"]["category"], "鞋类")
        self.assertEqual(updated["user"]["keywords"], ["运动鞋", "凉鞋"])

    def test_config_error_response_has_message_and_redacts_sensitive_value(self):
        response = config_error_response([{
            "field": "advanced.api_key",
            "reason": "不能返回密钥",
            "value": "secret",
            "allowed": "环境变量",
        }])

        self.assertFalse(response["ok"])
        self.assertEqual(response["errors"][0]["message"], "不能返回密钥")
        self.assertEqual(response["errors"][0]["value"], "***configured***")
        self.assertNotIn("secret", json.dumps(response, ensure_ascii=False))

    def test_settings_payload_maps_old_frontend_fields_to_user_config(self):
        patch = app.AppHandler.settings_payload_to_config_patch({
            "category": "凉鞋",
            "keywords": "凉鞋\n拖鞋",
            "min_price": "10",
            "max_price": "80",
            "weight_limit": "1.2",
            "profit_margin": "0.3",
            "image_mode": "original",
            "automation.mode": "collect_to_box",
        })

        self.assertEqual(patch["category"], "凉鞋")
        self.assertEqual(patch["purchase_price_min"], "10")
        self.assertEqual(patch["max_weight_kg"], "1.2")
        self.assertEqual(patch["minimum_profit_margin"], "0.3")
        self.assertEqual(patch["image_strategy"], "original")
        self.assertEqual(patch["run_mode"], "collect_to_box")

    def test_user_update_ignores_advanced_and_system_fields(self):
        save_config(self.root, {"keywords": ["鞋"], "max_items_per_run": 8})
        updated = update_config(self.root, {
            "target_count": 6,
            "advanced": {"cdp_port": 65530},
            "cdp_port": 65531,
            "system": {"platform": "Injected"},
        }, "user")

        self.assertEqual(updated["user"]["target_count"], 6)
        self.assertNotEqual(updated["advanced"]["cdp_port"], 65531)
        self.assertNotEqual(updated["system"]["platform"], "Injected")
        self.assertTrue(updated["_configWarnings"])

    def test_config_api_saves_user_values_and_returns_safe_config(self):
        with patch("app.get_runtime_system_status", return_value=RUNTIME_SYSTEM):
            response = self.handler().route_post("/api/config", {
                "values": {
                    "category": "凉鞋",
                    "keywords": ["凉鞋", "凉鞋", ""],
                    "target_count": 5,
                    "candidate_limit": 20,
                    "run_mode": "simulation",
                }
            })

        payload = response["payload"]
        self.assertEqual(response["status"], HTTPStatus.OK)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["config"]["user"]["category"], "凉鞋")
        self.assertEqual(payload["config"]["user"]["keywords"], ["凉鞋"])
        self.assertTrue(payload["config"]["system"]["chrome_detected"])
        self.assertTrue(payload["config"]["system"]["plugin_detected"])
        self.assertEqual(app.DB.setting("automation.mode"), "dry_run")

    def test_config_get_api_returns_safe_config_shape(self):
        handler = self.handler()
        handler.path = "/api/config"

        with patch("app.get_runtime_system_status", return_value=RUNTIME_SYSTEM):
            response = handler.do_GET()

        payload = response["payload"]
        self.assertEqual(response["status"], HTTPStatus.OK)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["config"]["version"], 1)
        self.assertIn("user", payload["config"])
        self.assertIn("advanced", payload["config"])
        self.assertTrue(payload["config"]["system"]["chrome_detected"])
        self.assertTrue(payload["config"]["system"]["alibaba_logged_in"])
        self.assertTrue(payload["config"]["system"]["miaoshou_logged_in"])

    def test_config_api_ignores_submitted_system_and_preserves_runtime_status(self):
        save_config(self.root, {"keywords": ["鞋"], "target_count": 5})

        with patch("app.get_runtime_system_status", return_value=RUNTIME_SYSTEM):
            response = self.handler().route_post("/api/config", {
                "values": {
                    "target_count": 6,
                    "system": {
                        "chrome_detected": False,
                        "token": "client-token",
                    },
                },
            })

        payload = response["payload"]
        saved = json.loads((self.root / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(response["status"], HTTPStatus.OK)
        self.assertEqual(load_config(self.root)["user"]["target_count"], 6)
        self.assertTrue(payload["config"]["system"]["chrome_detected"])
        self.assertNotIn("token", payload["config"]["system"])
        self.assertNotIn("system", saved)

    def test_config_api_rejects_invalid_user_config_without_writing(self):
        save_config(self.root, {"keywords": ["鞋"], "target_count": 5})
        before = load_config(self.root)["user"]["target_count"]

        response = self.handler().route_post("/api/config", {
            "values": {"target_count": "abc"}
        })

        self.assertEqual(response["status"], HTTPStatus.BAD_REQUEST)
        self.assertFalse(response["payload"]["ok"])
        self.assertEqual(response["payload"]["errors"][0]["field"], "user.target_count")
        self.assertIn("message", response["payload"]["errors"][0])
        self.assertEqual(load_config(self.root)["user"]["target_count"], before)

    def test_config_api_rejects_advanced_section_on_user_endpoint(self):
        response = self.handler().route_post("/api/config", {
            "section": "advanced",
            "values": {"cdp_port": 9444},
        })

        self.assertEqual(response["status"], HTTPStatus.BAD_REQUEST)
        self.assertFalse(response["payload"]["ok"])
        self.assertEqual(load_config(self.root)["advanced"]["cdp_port"], 9222)

    def test_advanced_config_api_updates_only_advanced_values(self):
        save_config(self.root, {"keywords": ["鞋"], "target_count": 5})

        with patch("app.get_runtime_system_status", return_value=RUNTIME_SYSTEM):
            response = self.handler().route_post("/api/config/advanced", {
                "values": {"cdp_port": 9444, "system": {"platform": "bad"}},
            })

        self.assertEqual(response["status"], HTTPStatus.OK)
        self.assertEqual(load_config(self.root)["advanced"]["cdp_port"], 9444)
        self.assertEqual(app.DB.setting("automation.cdp_port"), 9444)
        self.assertNotEqual(load_config(self.root)["system"]["platform"], "bad")
        self.assertEqual(response["payload"]["config"]["system"]["platform"], "Darwin")

    def test_advanced_config_api_rejects_core_safety_disable_without_sync(self):
        save_config(self.root, {"keywords": ["鞋"], "target_count": 5})
        app.DB.set_settings({"automation.cdp_port": 9222})
        before_config = (self.root / "config.json").read_text(encoding="utf-8")
        before_port = app.DB.setting("automation.cdp_port")

        response = self.handler().route_post("/api/config/advanced", {
            "values": {"cdp_port": 9444, "no_publish": False},
        })

        self.assertEqual(response["status"], HTTPStatus.BAD_REQUEST)
        self.assertFalse(response["payload"]["ok"])
        self.assertEqual(response["payload"]["errors"][0]["field"], "advanced.no_publish")
        self.assertEqual((self.root / "config.json").read_text(encoding="utf-8"), before_config)
        self.assertEqual(app.DB.setting("automation.cdp_port"), before_port)

    def test_settings_api_compat_maps_old_fields_without_deleting_new_config(self):
        save_config(self.root, {"keywords": ["运动鞋"], "category": "鞋类", "target_count": 5})

        response = self.handler().route_post("/api/settings", {
            "category": "凉鞋",
            "automation.mode": "collect_to_box",
        })

        config = load_config(self.root)
        self.assertEqual(response["status"], HTTPStatus.OK)
        self.assertTrue(response["payload"]["deprecated"])
        self.assertEqual(config["user"]["category"], "凉鞋")
        self.assertEqual(config["user"]["keywords"], ["运动鞋"])
        self.assertEqual(config["user"]["run_mode"], "collect_to_box")
        self.assertEqual(app.DB.setting("automation.mode"), "live")

    def test_settings_api_does_not_directly_write_mirrored_config_keys(self):
        save_config(self.root, {"keywords": ["运动鞋"], "category": "鞋类", "target_count": 5})

        response = self.handler().route_post("/api/settings", {
            "automation.cdp_port": 9555,
            "automation.chrome_profile_dir": "data/old-profile",
            "image.timeout": 77,
        })

        config = load_config(self.root)
        self.assertEqual(response["status"], HTTPStatus.OK)
        self.assertEqual(config["advanced"]["cdp_port"], 9555)
        self.assertEqual(app.DB.setting("automation.cdp_port"), 9555)
        self.assertEqual(app.DB.setting("automation.chrome_profile_dir"), "data/old-profile")
        self.assertEqual(app.DB.setting("image.timeout"), 77)

    def test_settings_payload_converts_legacy_margin_percent(self):
        self.assertEqual(app.AppHandler.settings_payload_to_config_patch({"market.target_margin_pct": "20"})["minimum_profit_margin"], 0.2)
        self.assertEqual(app.AppHandler.settings_payload_to_config_patch({"market.target_margin_pct": 20})["minimum_profit_margin"], 0.2)

    def test_settings_payload_rejects_invalid_legacy_margin(self):
        for value in ("abc", "", None):
            with self.subTest(value=value):
                with self.assertRaises(ConfigValidationError) as ctx:
                    app.AppHandler.settings_payload_to_config_patch({"market.target_margin_pct": value})

                self.assertEqual(ctx.exception.errors[0]["field"], "market.target_margin_pct")

    def test_settings_api_rejects_invalid_margin_without_partial_save(self):
        for value in ("abc", "", None):
            with self.subTest(value=value):
                save_config(self.root, {"keywords": ["运动鞋"], "category": "鞋类", "target_count": 5})
                app.DB.set_settings({"market.target_margin_pct": 22, "automation.mode": "dry_run"})
                before_config = (self.root / "config.json").read_text(encoding="utf-8")
                before_settings = app.DB.settings()

                response = self.handler().route_post("/api/settings", {
                    "category": "凉鞋",
                    "market.target_margin_pct": value,
                    "automation.mode": "collect_to_box",
                })

                self.assertEqual(response["status"], HTTPStatus.BAD_REQUEST)
                self.assertFalse(response["payload"]["ok"])
                self.assertEqual(response["payload"]["errors"][0]["field"], "market.target_margin_pct")
                self.assertEqual((self.root / "config.json").read_text(encoding="utf-8"), before_config)
                self.assertEqual(app.DB.settings(), before_settings)

    def test_settings_api_saves_valid_margin_percent(self):
        save_config(self.root, {"keywords": ["运动鞋"], "category": "鞋类", "target_count": 5})

        response = self.handler().route_post("/api/settings", {
            "market.target_margin_pct": "20",
        })

        self.assertEqual(response["status"], HTTPStatus.OK)
        self.assertEqual(load_config(self.root)["user"]["minimum_profit_margin"], 0.2)
        self.assertEqual(app.DB.setting("market.target_margin_pct"), 20.0)


if __name__ == "__main__":
    unittest.main()
