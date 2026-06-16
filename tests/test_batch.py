import tempfile
import time
import unittest
import uuid
import json
from pathlib import Path
from unittest.mock import patch

import app
from lib.database import Database


class BatchGateTest(unittest.TestCase):
    def setUp(self):
        self.original_db = app.DB
        app.DB = Database(Path(tempfile.mkdtemp()) / "test.db")
        self.db = app.DB
        self.product = self.db.save_product({
            "sourceProductId": "123", "sourceUrl": "https://detail.1688.com/offer/123.html",
            "title": "运动鞋", "sku": "SKU-1", "category": "运动鞋", "costPrice": 30,
        })
        app.create_market_versions(self.product["id"])
        self.db.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,prompt,created_at) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, self.product["id"], "/assets/test.jpg", "uploaded", 1, "", int(time.time())),
        )
        self.shop_id = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO shops(id,account_name,entity_name,shop_name,market,warehouse,default_inventory,price_multiplier,enabled) VALUES (?,?,?,?,?,?,?,?,?)",
            (self.shop_id, "account", "entity", "MY shop", "MY", "warehouse", 20, 1, 1),
        )

    def tearDown(self):
        app.DB = self.original_db

    def make_batch(self, batch_id):
        return {"id": batch_id, "product_ids": [self.product["id"]], "shop_ids": [self.shop_id]}

    def insert_batch(self, batch_id="batch-1", dry_run=True, status="preparing"):
        now = int(time.time())
        preview = app.batch_preflight(self.make_batch(batch_id))
        self.db.execute(
            "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                batch_id, "五国运动户外铺货", status, int(dry_run),
                "[\"%s\"]" % self.product["id"], "[\"%s\"]" % self.shop_id,
                json.dumps(app.batch_summary_from_preview(preview), ensure_ascii=False),
                now, now,
            ),
        )
        return self.db.row("SELECT * FROM batches WHERE id=?", (batch_id,))

    def test_complete_batch_passes_and_reserves_idempotency_key(self):
        batch = self.make_batch("batch-1")
        self.assertEqual(app.validate_batch(batch), [])
        self.assertEqual(app.reserve_publish_keys(batch), [])
        keys = self.db.rows("SELECT * FROM publish_keys")
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0]["status"], "reserved")

    def test_batch_preflight_returns_ready_summary_for_valid_batch(self):
        preview = app.batch_preflight(self.make_batch("batch-1"))

        self.assertTrue(preview["ready"])
        self.assertEqual(preview["productCount"], 1)
        self.assertEqual(preview["shopCount"], 1)
        self.assertEqual(preview["taskCount"], 1)
        self.assertEqual(preview["errors"], 0)
        self.assertEqual(app.batch_summary_from_preview(preview)["publishTasks"], 1)

    def test_batch_confirmation_summary_requires_waiting_run(self):
        batch = self.insert_batch()
        summary = app.batch_confirmation_summary(batch)

        self.assertFalse(summary["canConfirm"])
        self.assertEqual(summary["phrase"], "CONFIRM 1x1 DRY")
        self.assertEqual(summary["summary"]["publishTasks"], 1)

    def test_batch_confirmation_summary_allows_waiting_run(self):
        batch = self.insert_batch()
        self.db.create_run("publish", ["等待人工确认"], batch_id=batch["id"], status="waiting_confirmation")

        summary = app.batch_confirmation_summary(batch)

        self.assertTrue(summary["canConfirm"])
        self.assertEqual(summary["mode"], "演练模式")

    def test_batch_confirm_rejects_missing_confirmation_phrase(self):
        batch = self.insert_batch()

        with self.assertRaises(ValueError):
            app.require_batch_confirmation(batch, {"confirmation": ""})

    def test_batch_confirm_helper_requires_phrase_before_enqueue(self):
        batch = self.insert_batch()
        run = self.db.create_run("publish", ["等待人工确认"], batch_id=batch["id"], status="waiting_confirmation")

        with patch("app.enqueue_automation_run", return_value=True) as enqueue:
            result = app.confirm_batch(batch["id"], {"confirmation": app.batch_confirmation_phrase(batch)})

        refreshed = self.db.get_run(run["id"])
        self.assertEqual(result["batch"]["status"], "confirmed")
        self.assertEqual(refreshed["status"], "queued")
        self.assertEqual(refreshed["context"]["phase"], "confirm")
        enqueue.assert_called_once_with(run["id"], confirm=True)

    def test_batch_confirm_helper_rejects_wrong_phrase(self):
        batch = self.insert_batch()
        self.db.create_run("publish", ["等待人工确认"], batch_id=batch["id"], status="waiting_confirmation")

        with self.assertRaises(ValueError):
            app.confirm_batch(batch["id"], {"confirmation": "wrong"})

    def test_batch_confirmation_api_returns_summary(self):
        batch = self.insert_batch()
        summary = app.batch_confirmation_summary(batch)

        self.assertEqual(summary["phrase"], "CONFIRM 1x1 DRY")
        self.assertIn("summary", summary)
        self.assertIn("dryRunReport", summary)

    def test_dry_run_report_includes_batch_counts_and_recommendation(self):
        batch = self.insert_batch()
        self.db.create_run("publish", ["检查批次完整性", "等待人工确认"], batch_id=batch["id"], status="completed")

        report = app.batch_report(batch)

        self.assertEqual(report["batchId"], batch["id"])
        self.assertEqual(report["products"], 1)
        self.assertEqual(report["shops"], 1)
        self.assertEqual(report["tasks"], 1)
        self.assertEqual(report["successSteps"], 1)
        self.assertTrue(report["suggestLivePublish"])

    def test_live_publish_requires_dry_run_or_explicit_skip(self):
        batch = self.insert_batch("live-batch", dry_run=False)
        self.db.create_run("publish", ["等待人工确认"], batch_id=batch["id"], status="waiting_confirmation")

        with self.assertRaises(ValueError):
            app.confirm_batch(batch["id"], {"confirmation": app.batch_confirmation_phrase(batch)})

        with self.assertRaisesRegex(ValueError, "no_publish=true"):
            app.confirm_batch(batch["id"], {"confirmation": "CONFIRM 1x1 LIVE", "skipDryRun": True})

    @patch("app.workbench_config", return_value={"no_publish": False})
    def test_live_publish_accepts_explicit_skip_when_safety_allows(self, _config):
        batch = self.insert_batch("live-batch", dry_run=False)
        self.db.create_run("publish", ["等待人工确认"], batch_id=batch["id"], status="waiting_confirmation")

        with patch("app.enqueue_automation_run", return_value=True):
            result = app.confirm_batch(batch["id"], {"confirmation": "CONFIRM 1x1 LIVE", "skipDryRun": True})

        self.assertEqual(result["batch"]["status"], "confirmed")
        self.assertTrue(self.db.get_run(result["run"]["id"])["context"]["skipDryRun"])

    @patch("app.workbench_config", return_value={"no_publish": False})
    def test_live_publish_accepts_matching_completed_dry_run(self, _config):
        dry = self.insert_batch("dry-batch", dry_run=True, status="completed_dry_run")
        self.db.create_run("publish", ["演练完成"], batch_id=dry["id"], status="completed")
        live = self.insert_batch("live-batch", dry_run=False)
        self.db.create_run("publish", ["等待人工确认"], batch_id=live["id"], status="waiting_confirmation")

        summary = app.batch_confirmation_summary(live)

        self.assertTrue(summary["canConfirm"])
        self.assertEqual(summary["phrase"], "CONFIRM 1x1 LIVE")
        self.assertEqual(summary["liveGate"]["dryRunReport"]["batchId"], dry["id"])

    def test_batch_preflight_reports_missing_image_blocked_market_and_price(self):
        self.db.execute("DELETE FROM assets WHERE product_id=?", (self.product["id"],))
        self.db.execute(
            "UPDATE market_versions SET blocked=1,block_reasons='[\"侵权风险\"]',sale_price=0 WHERE product_id=? AND market='MY'",
            (self.product["id"],),
        )

        preview = app.batch_preflight(self.make_batch("batch-1"))
        categories = {item["category"] for item in preview["risks"]}

        self.assertFalse(preview["ready"])
        self.assertIn("missing_image", categories)
        self.assertIn("blocked_market", categories)
        self.assertIn("price", categories)
        self.assertEqual(preview["counts"]["missing_image"], 1)

    def test_batch_preflight_reports_inventory_and_warehouse_risks(self):
        self.db.execute("UPDATE shops SET warehouse='',default_inventory=0 WHERE id=?", (self.shop_id,))
        self.db.execute(
            "UPDATE market_versions SET warehouse='',inventory=0 WHERE product_id=? AND market='MY'",
            (self.product["id"],),
        )

        preview = app.batch_preflight(self.make_batch("batch-1"))
        categories = {item["category"] for item in preview["risks"]}

        self.assertFalse(preview["ready"])
        self.assertIn("warehouse", categories)
        self.assertIn("inventory", categories)

    def test_batch_preflight_reports_warning_status_without_blocking(self):
        self.db.execute(
            "UPDATE market_versions SET title='短题',sale_price=30,warehouse='warehouse',inventory=20 WHERE product_id=? AND market='MY'",
            (self.product["id"],),
        )

        preview = app.batch_preflight(self.make_batch("batch-1"))
        categories = {item["category"] for item in preview["risks"]}

        self.assertTrue(preview["ready"])
        self.assertEqual(preview["status"], "warning")
        self.assertGreaterEqual(preview["warningCount"], 1)
        self.assertIn("short_title", categories)
        self.assertIn("margin", categories)
        self.assertEqual(preview["blockingCount"], 0)
        self.assertEqual(preview["versionCount"], 1)

    def test_batch_preflight_blocks_disabled_shop(self):
        self.db.execute("UPDATE shops SET enabled=0 WHERE id=?", (self.shop_id,))

        preview = app.batch_preflight(self.make_batch("batch-1"))
        categories = {item["category"] for item in preview["risks"]}

        self.assertFalse(preview["ready"])
        self.assertEqual(preview["status"], "blocked")
        self.assertIn("shop_disabled", categories)

    def test_create_batch_from_payload_uses_preflight_gate(self):
        self.db.execute("DELETE FROM assets WHERE product_id=?", (self.product["id"],))

        batch, preview, error = app.create_batch_from_payload({
            "name": "缺图批次",
            "productIds": [self.product["id"]],
            "shopIds": [self.shop_id],
            "dryRun": True,
        })

        self.assertIsNone(batch)
        self.assertFalse(preview["ready"])
        self.assertIn("缺少审核通过的图片", error)
        self.assertFalse(self.db.rows("SELECT * FROM batches WHERE name='缺图批次'"))

    def test_published_product_blocks_other_batch(self):
        first = self.make_batch("batch-1")
        app.reserve_publish_keys(first)
        self.db.execute("UPDATE publish_keys SET status='published'")
        duplicates = app.reserve_publish_keys(self.make_batch("batch-2"))
        self.assertEqual(len(duplicates), 1)

    def test_batch_preflight_reports_duplicate_publish_risk(self):
        first = self.make_batch("batch-1")
        app.reserve_publish_keys(first)
        self.db.execute("UPDATE publish_keys SET status='published'")

        preview = app.batch_preflight(self.make_batch("batch-2"))

        self.assertFalse(preview["ready"])
        self.assertEqual(preview["counts"]["duplicate"], 1)
        self.assertIn("重复铺货", preview["risks"][0]["message"])

    def test_hard_block_cannot_be_manually_unchecked(self):
        self.db.execute(
            "UPDATE market_versions SET blocked=1,block_reasons='[\"侵权风险\"]' WHERE product_id=? AND market='MY'",
            (self.product["id"],),
        )
        result = self.db.save_market_version(self.product["id"], "MY", {"blocked": False})
        self.assertTrue(result["blocked"])


if __name__ == "__main__":
    unittest.main()
