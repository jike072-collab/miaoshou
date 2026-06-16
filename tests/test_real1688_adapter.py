import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.browser_manager import BrowserManager
from lib.database import Database
from lib.local_config import save_config
from lib.real1688_adapter import Real1688Adapter


class Real1688AdapterTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.db = Database(self.root / "test.db")
        save_config(self.root, {
            "mode": "real",
            "dry_run_collect": True,
            "no_publish": True,
            "keywords": ["运动鞋", "凉鞋"],
            "max_pages_per_keyword": 2,
            "max_items_per_run": 10,
        })
        self.browser = BrowserManager(self.db, self.root)
        self.adapter = Real1688Adapter(self.db, self.root, self.browser)

    def test_sourcing_run_round_trip(self):
        run = self.db.create_sourcing_run()
        updated = self.db.update_sourcing_run(
            run["run_id"],
            status="searching",
            current_keyword="运动鞋",
            current_page=1,
            found_count=3,
            saved_count=2,
            skipped_count=1,
        )

        self.assertEqual(updated["status"], "searching")
        self.assertEqual(updated["current_keyword"], "运动鞋")
        self.assertEqual(updated["found_count"], 3)
        self.assertEqual(self.db.latest_sourcing_run()["run_id"], run["run_id"])

    def test_current_does_not_create_empty_run(self):
        current = self.adapter.current()

        self.assertEqual(current["status"], "idle")
        self.assertEqual(current["run_id"], "")
        self.assertIsNone(self.db.latest_sourcing_run())

    def test_save_results_persists_real_1688_fields(self):
        saved, skipped, failed = self.adapter.save_results([{
            "title": "夏季透气运动鞋",
            "url": "https://detail.1688.com/offer/123456.html",
            "offer_id": "123456",
            "main_image_url": "https://cbu01.alicdn.com/img/test.jpg",
            "price": 29.8,
            "min_order": 2,
            "sales_text": "已售 3000 件",
            "monthly_sales": 3000,
            "supplier_name": "晋江鞋业",
            "shop_url": "https://shop.1688.com/",
            "origin_place": "福建泉州",
            "category": "运动鞋",
            "search_page": 1,
            "search_rank": 4,
        }], "运动鞋")

        candidate = self.db.list_candidates()[0]
        self.assertEqual((saved, skipped, failed), (1, 0, 0))
        self.assertEqual(candidate["source_product_id"], "123456")
        self.assertEqual(candidate["title"], "夏季透气运动鞋")
        self.assertEqual(candidate["source_price"], 29.8)
        self.assertEqual(candidate["min_order"], 2)
        self.assertEqual(candidate["sales_text"], "已售 3000 件")
        self.assertEqual(candidate["monthly_sales"], 3000)
        self.assertEqual(candidate["supplier_name"], "晋江鞋业")
        self.assertEqual(candidate["shop_url"], "https://shop.1688.com/")
        self.assertEqual(candidate["origin_place"], "福建泉州")
        self.assertEqual(candidate["keyword"], "运动鞋")
        self.assertEqual(candidate["search_page"], 1)
        self.assertEqual(candidate["search_rank"], 4)
        self.assertEqual(candidate["images"], ["https://cbu01.alicdn.com/img/test.jpg"])

    def test_duplicate_search_result_is_counted_as_skipped(self):
        item = {
            "title": "夏季透气运动鞋",
            "url": "https://detail.1688.com/offer/123456.html",
            "offer_id": "123456",
            "main_image_url": "https://cbu01.alicdn.com/img/test.jpg",
            "price": 29.8,
        }
        self.adapter.save_results([item], "运动鞋")
        saved, skipped, failed = self.adapter.save_results([item], "运动鞋")

        self.assertEqual((saved, skipped, failed), (0, 1, 0))
        self.assertEqual(len(self.db.list_candidates()), 1)

    def test_duplicate_offer_id_with_different_url_is_skipped(self):
        first = {
            "title": "夏季透气运动鞋",
            "url": "https://detail.1688.com/offer/123456.html",
            "offer_id": "123456",
            "main_image_url": "https://cbu01.alicdn.com/img/test.jpg",
        }
        second = {
            "title": "夏季透气运动鞋",
            "url": "https://detail.m.1688.com/page/index.html?offerId=123456&spm=a260k",
            "offer_id": "123456",
            "main_image_url": "https://cbu01.alicdn.com/img/test-2.jpg",
        }

        self.adapter.save_results([first], "运动鞋")
        saved, skipped, failed = self.adapter.save_results([second], "运动鞋")

        self.assertEqual((saved, skipped, failed), (0, 1, 0))
        self.assertEqual(len(self.db.list_candidates()), 1)

    def test_run_once_pauses_when_platform_requires_manual(self):
        run = self.adapter.start_run()
        with patch.object(self.adapter, "ensure_alibaba_ready", side_effect=Exception("boom")):
            result = self.adapter.run_once(run["run_id"])

        self.assertEqual(result["status"], "failed")
        self.assertIn("boom", result["error"])

    def test_run_once_pauses_on_extraction_verification(self):
        run = self.adapter.start_run()
        with patch.object(self.adapter, "ensure_alibaba_ready", return_value=True), \
                patch.object(self.adapter, "extract", return_value={"verification_required": True, "error": "1688 出现验证码"}):
            result = self.adapter.run_once(run["run_id"])

        self.assertEqual(result["status"], "waiting_for_manual")
        self.assertIn("验证码", result["error"])

    def test_run_once_respects_config_limits(self):
        run = self.adapter.start_run()
        extracted = [{
            "title": "夏季透气运动鞋",
            "url": "https://detail.1688.com/offer/100001.html",
            "offer_id": "100001",
            "main_image_url": "https://cbu01.alicdn.com/img/test.jpg",
            "price": 29.8,
        }]
        with patch.object(self.adapter, "ensure_alibaba_ready", return_value=True), \
                patch.object(self.adapter, "extract", return_value={"items": extracted}) as extract:
            result = self.adapter.run_once(run["run_id"])

        self.assertEqual(result["status"], "completed")
        self.assertGreaterEqual(extract.call_count, 1)
        self.assertEqual(result["saved_count"], 1)
        self.assertLessEqual(result["saved_count"], 10)

    def test_extract_updates_the_requested_run(self):
        first = self.adapter.start_run()
        second = self.db.create_sourcing_run()
        response = {"ok": True, "items": []}

        class Completed:
            returncode = 0
            stdout = "\n" + json.dumps(response)
            stderr = ""

        with patch.object(self.browser, "debug_port", return_value=9222), \
                patch("lib.real1688_adapter.subprocess.run", return_value=Completed()):
            result = self.adapter.extract(first["run_id"], "运动鞋", 1, 3)

        self.assertEqual(result, response)
        self.assertEqual(self.db.get_sourcing_run(first["run_id"])["status"], "extracting_results")
        self.assertEqual(self.db.get_sourcing_run(second["run_id"])["status"], "idle")

    def test_extract_raises_when_runner_reports_failure(self):
        run = self.adapter.start_run()

        class Completed:
            returncode = 1
            stdout = json.dumps({"ok": False, "error": "CDP 未连接"})
            stderr = ""

        with patch.object(self.browser, "debug_port", return_value=9222), \
                patch("lib.real1688_adapter.subprocess.run", return_value=Completed()):
            with self.assertRaisesRegex(RuntimeError, "CDP 未连接"):
                self.adapter.extract(run["run_id"], "运动鞋", 1, 3)


if __name__ == "__main__":
    unittest.main()
