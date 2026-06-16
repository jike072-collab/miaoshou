import tempfile
import unittest
from pathlib import Path

from lib.automation import AutomationEngine
from lib.database import Database
from lib.local_config import assert_publish_allowed, config_status, ensure_local_runtime, load_config, save_config


class LocalConfigTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_bootstrap_creates_config_and_runtime_dirs(self):
        ensure_local_runtime(self.root)
        config = load_config(self.root)

        self.assertTrue((self.root / "logs").is_dir())
        self.assertTrue((self.root / "screenshots").is_dir())
        self.assertTrue((self.root / "images").is_dir())
        self.assertTrue((self.root / "chrome-profile").is_dir())
        self.assertTrue((self.root / "config.json").is_file())
        self.assertTrue((self.root / "config.example.json").is_file())
        self.assertTrue((self.root / "workbench.token").is_file())
        self.assertTrue(config["dry_run_collect"])
        self.assertTrue(config["no_publish"])

    def test_config_status_reports_collect_allowed_and_publish_forbidden(self):
        config = save_config(self.root, {"mode": "real", "dry_run_collect": True, "no_publish": True})
        status = config_status(config)

        self.assertEqual(status["mode"], "real")
        self.assertTrue(status["allowCollect"])
        self.assertTrue(status["publishForbidden"])
        self.assertEqual(status["maxItemsPerRun"], 10)

    def test_publish_recipe_is_blocked_when_no_publish_enabled(self):
        config = load_config(self.root)

        with self.assertRaisesRegex(RuntimeError, "no_publish=true"):
            assert_publish_allowed(config, [{"type": "clickText", "text": "确认发布"}], "发布动作配方")

        self.assertTrue(assert_publish_allowed(config, [{"type": "fill", "selector": "#title", "value": "鞋"}], "草稿动作"))

    def test_live_confirm_publish_is_blocked_by_default(self):
        db = Database(self.root / "test.db")
        db.set_settings({"automation.mode": "live", "automation.publish_recipe": [{"type": "fill", "selector": "#title", "value": "鞋"}]})
        now = 1
        db.execute(
            "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("batch", "test", "draft", 0, "[]", "[]", "{}", now, now),
        )
        engine = AutomationEngine(db, self.root)
        run = engine.create_publish_run("batch")

        result = engine.confirm_publish(run["id"])

        self.assertEqual(result["status"], "blocked")
        self.assertIn("no_publish=true", result["error"])
        self.assertEqual(result["diagnostics"]["failedStep"], "no_publish 安全拦截")


if __name__ == "__main__":
    unittest.main()
