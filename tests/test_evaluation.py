import unittest

from lib.evaluation import evaluate_candidate, evaluation_status


class EvaluationTest(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "category": "运动鞋", "source_price": 30, "weight_g": 800,
            "monthly_sales": 1000, "repurchase_rate": 20, "rating": 4.8,
            "supplier_years": 5, "dispatch_hours": 48, "image_count": 6,
            "sku_complete": True, "risk_flags": [],
        }

    def test_qualified_market_with_complete_data(self):
        results = evaluate_candidate(self.candidate, {
            "markets": {"MY": {"targetPriceCny": 140, "trend": 80, "salesSignal": 80, "competition": 30, "dataComplete": True}}
        })
        malaysia = next(item for item in results if item["market"] == "MY")
        self.assertGreaterEqual(malaysia["total_score"], 70)
        self.assertGreaterEqual(malaysia["confidence"], 70)
        self.assertEqual(evaluation_status(results), "已达标")

    def test_incomplete_sku_is_hard_block(self):
        self.candidate["sku_complete"] = False
        results = evaluate_candidate(self.candidate)
        self.assertTrue(all("颜色或尺码规格不完整" in item["hard_blocks"] for item in results))

    def test_missing_market_samples_cannot_auto_collect(self):
        results = evaluate_candidate(self.candidate)
        self.assertTrue(all(item["confidence"] < 70 for item in results))
        self.assertEqual(evaluation_status(results), "待确认")

    def test_unsupported_category_is_hard_block(self):
        self.candidate["category"] = "食品"
        results = evaluate_candidate(self.candidate)
        self.assertTrue(all("类目不在首版支持范围" in item["hard_blocks"] for item in results))


if __name__ == "__main__":
    unittest.main()
