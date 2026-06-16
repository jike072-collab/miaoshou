import unittest

from lib.title_cleaner import TitleCleaner


class TitleCleanerTest(unittest.TestCase):
    def setUp(self):
        self.cleaner = TitleCleaner()

    def test_removes_supply_terms_and_outputs_english_title(self):
        result = self.cleaner.clean("跨境外贸一键代发夏季透气运动鞋厂家直销")

        self.assertEqual(result["status"], "title_cleaned")
        self.assertEqual(result["clean_title"], "Breathable Summer Sports Shoes")
        self.assertEqual(result["removed_terms"], ["跨境", "外贸", "一键代发", "厂家直销"])
        self.assertEqual(result["risk_terms"], [])
        for term in ("跨境", "外贸", "一键代发", "厂家直销"):
            self.assertNotIn(term, result["clean_title"])

    def test_removes_platform_and_risk_marketing_terms(self):
        result = self.cleaner.clean("1688淘宝正品大牌高仿复刻防滑跑鞋")

        self.assertEqual(result["clean_title"], "Non Slip Running Shoes")
        self.assertIn("1688", result["removed_terms"])
        self.assertIn("淘宝", result["removed_terms"])
        self.assertIn("高仿", result["risk_terms"])
        self.assertIn("复刻", result["risk_terms"])
        self.assertNotIn("高仿", result["clean_title"])


if __name__ == "__main__":
    unittest.main()
