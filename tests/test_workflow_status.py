import tempfile
import unittest
from pathlib import Path

import app
from lib.database import Database


class WorkflowStatusTest(unittest.TestCase):
    def setUp(self):
        self.original_db = app.DB
        self.root = Path(tempfile.mkdtemp())
        app.DB = Database(self.root / "test.db")

    def tearDown(self):
        app.DB = self.original_db

    def candidate(self, **updates):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/900001.html"])[0]
        defaults = {
            "title": "夏季透气运动鞋",
            "category": "运动鞋",
            "source_price": 39,
            "weight_g": 650,
            "monthly_sales": 1000,
            "rating": 4.8,
            "dispatch_hours": 24,
            "image_count": 3,
            "images": ["https://example.com/a.jpg", "https://example.com/b.jpg", "https://example.com/c.jpg"],
            "sku_complete": True,
        }
        defaults.update(updates)
        return app.DB.update_candidate(candidate["id"], defaults)

    def save_collectable_evaluations(self, candidate_id):
        app.DB.save_evaluations(candidate_id, [
            {
                "market": market,
                "demand_score": 80,
                "sales_score": 80,
                "profit_score": 80,
                "competition_score": 80,
                "logistics_score": 80,
                "supply_score": 80,
                "media_score": 80,
                "total_score": 80,
                "confidence": 85,
                "hard_blocks": [],
                "reasons": ["达标"],
                "metrics": {"target_price_cny": 150, "market_data_complete": True},
            }
            for market in app.MARKETS
        ])

    def test_duplicate_candidate_goes_to_failure_handling(self):
        candidate = self.candidate(dedupe_status="duplicate_offer_id", dedupe_reason="已存在同 offer_id 候选")

        status = app.get_candidate_workflow_status(app.DB.get_candidate(candidate["id"]))

        self.assertEqual(status["stage"], "failure_handling")
        self.assertTrue(status["blocked"])
        self.assertTrue(status["failed"])
        self.assertIn("offer_id", status["detail"])

    def test_risk_blocked_candidate_explains_precheck_reason(self):
        candidate = self.candidate(title="正品大牌高仿复刻跑鞋")
        app.precheck_candidates([candidate["id"]])

        status = app.get_candidate_workflow_status(app.DB.get_candidate(candidate["id"]))

        self.assertEqual(status["stage"], "failure_handling")
        self.assertTrue(status["blocked"])
        self.assertIn("品牌侵权", status["detail"])

    def test_precheck_passed_but_image_not_ready_blocks_miaoshou_collection(self):
        candidate = self.candidate(
            clean_title="Breathable Summer Sports Shoes",
            title_cleaned_at=1,
            image_status="needs_generation",
            image_reason="存在平台水印",
        )
        app.precheck_candidates([candidate["id"]])
        self.save_collectable_evaluations(candidate["id"])

        status = app.get_candidate_workflow_status(app.DB.get_candidate(candidate["id"]))

        self.assertEqual(status["stage"], "image_needs_generation")
        self.assertTrue(status["blocked"])
        self.assertIn("平台水印", status["detail"])

    def test_collection_box_record_marks_candidate_collected(self):
        candidate = self.candidate(clean_title="Breathable Summer Sports Shoes", title_cleaned_at=1, image_status="image_ready", collected_at=123)
        app.precheck_candidates([candidate["id"]])
        self.save_collectable_evaluations(candidate["id"])

        status = app.get_candidate_workflow_status(app.DB.get_candidate(candidate["id"]))

        self.assertEqual(status["stage"], "product_collected")
        self.assertFalse(status["blocked"])


if __name__ == "__main__":
    unittest.main()
