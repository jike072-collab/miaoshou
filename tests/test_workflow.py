import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from lib.database import Database


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.original_db = app.DB
        app.DB = Database(Path(tempfile.mkdtemp()) / "test.db")

    def tearDown(self):
        app.DB = self.original_db

    def test_collection_completion_creates_one_product_and_five_markets(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "source_product_id": "998877", "title": "轻量运动包", "category": "运动包",
            "source_price": 28, "weight_g": 650, "images": ["https://example.com/bag.jpg"],
        })

        first = app.ensure_product_from_candidate(candidate["id"])
        second = app.ensure_product_from_candidate(candidate["id"])

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(app.DB.list_products()), 1)
        self.assertEqual(len(app.DB.market_versions(first["id"])), 5)
        self.assertEqual(first["mainImage"], "https://example.com/bag.jpg")

    def test_refresh_candidate_from_source_populates_core_fields(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        with patch("app.scrape_product", return_value={
            "title": "网面透气运动鞋女2026新款",
            "category": "",
            "sourcePrice": 39.8,
            "weightG": 880,
            "images": ["https://example.com/a.jpg", "https://example.com/b.jpg"],
        }):
            refreshed = app.refresh_candidate_from_source(candidate["id"])

        self.assertEqual(refreshed["title"], "网面透气运动鞋女2026新款")
        self.assertEqual(refreshed["category"], "运动鞋")
        self.assertEqual(refreshed["source_price"], 39.8)
        self.assertEqual(refreshed["weight_g"], 880)
        self.assertEqual(refreshed["image_count"], 2)
        self.assertEqual(refreshed["status"], "待确认")

    def test_refresh_candidate_preserves_existing_images_when_source_has_none(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "title": "运动鞋",
            "images": ["https://example.com/search.jpg"],
            "image_count": 1,
        })
        with patch("app.scrape_product", return_value={
            "title": "亲，请按照说明进行验证哦",
            "category": "",
            "sourcePrice": 0,
            "weightG": 0,
            "images": [],
        }):
            refreshed = app.refresh_candidate_from_source(candidate["id"])

        self.assertEqual(refreshed["title"], "运动鞋")
        self.assertEqual(refreshed["images"], ["https://example.com/search.jpg"])
        self.assertEqual(refreshed["image_count"], 1)

    def test_system_selfcheck_reports_business_readiness_gaps(self):
        app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        result = app.system_selfcheck()
        checks = {item["id"]: item for item in result["checks"]}

        self.assertEqual(checks["candidate_pool"]["status"], "pass")
        self.assertEqual(checks["candidate_supply_data"]["status"], "warn")
        self.assertEqual(checks["qualified_candidates"]["status"], "warn")
        self.assertEqual(checks["product_pool"]["status"], "warn")
        self.assertTrue(result["nextSteps"]["automatic"])

    def test_bulk_refresh_sources_reports_partial_errors(self):
        first = app.DB.import_candidates(["https://detail.1688.com/offer/111.html"])[0]
        second = app.DB.import_candidates(["https://detail.1688.com/offer/222.html"])[0]

        def fake_refresh(candidate_id):
            if candidate_id == second["id"]:
                raise RuntimeError("验证页")
            app.DB.update_candidate(candidate_id, {"title": "运动鞋", "category": "运动鞋"})
            return app.candidate_summary(app.DB.get_candidate(candidate_id))

        with patch("app.refresh_candidate_from_source", side_effect=fake_refresh):
            result = app.refresh_candidates_from_sources([first["id"], second["id"], "missing"])

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(result["items"][0]["title"], "运动鞋")
        self.assertIn("验证页", result["errors"][0]["error"])

    def test_selfcheck_repair_creates_product_and_approved_asset(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "title": "轻量运动包",
            "category": "运动包",
            "source_price": 28,
            "weight_g": 650,
            "monthly_sales": 1000,
            "repurchase_rate": 20,
            "rating": 4.8,
            "supplier_years": 5,
            "dispatch_hours": 48,
            "image_count": 1,
            "sku_complete": True,
            "images": ["https://example.com/bag.jpg"],
        })
        evaluations = app.evaluate_candidate(app.DB.get_candidate(candidate["id"]), {
            "markets": {"MY": {"targetPriceCny": 140, "trend": 82, "salesSignal": 82, "competition": 30, "dataComplete": True}}
        })
        app.DB.save_evaluations(candidate["id"], evaluations)
        with patch("app.fetch_image", return_value=(b"fake-image-bytes", "image/jpeg")):
            result = app.selfcheck_repair()

        self.assertTrue(result["actions"])
        self.assertTrue(app.DB.list_products())
        self.assertTrue(app.DB.rows("SELECT * FROM assets WHERE approved=1"))
        self.assertFalse(result["after"]["readyForLive"])
        self.assertIn("manual", result["nextSteps"])
        self.assertEqual(app.DB.get_candidate(candidate["id"])["status"], "已达标")

    def test_selfcheck_repair_limits_source_refresh(self):
        candidates = app.DB.import_candidates([
            "https://detail.1688.com/offer/111.html",
            "https://detail.1688.com/offer/222.html",
            "https://detail.1688.com/offer/333.html",
        ])
        calls = []

        def fake_refresh(candidate_id):
            calls.append(candidate_id)
            item = app.DB.update_candidate(candidate_id, {"title": "运动鞋", "category": "运动鞋", "image_count": 1})
            return app.candidate_summary(item)

        with patch("app.refresh_candidate_from_source", side_effect=fake_refresh):
            result = app.selfcheck_repair(max_refresh=2)

        self.assertEqual(len(calls), 2)
        self.assertTrue(any("仍有 1 个候选待批量补全" in action for action in result["actions"]))
        self.assertEqual(calls, [candidates[0]["id"], candidates[1]["id"]])


if __name__ == "__main__":
    unittest.main()
