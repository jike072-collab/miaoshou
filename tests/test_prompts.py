import unittest

from lib.prompts import build_prompts


class PromptTest(unittest.TestCase):
    def test_standard_preset_has_three_strict_prompts(self):
        prompts = build_prompts("运动鞋", "standard")
        self.assertEqual(len(prompts), 3)
        self.assertTrue(all("Strictly preserve" in prompt for prompt in prompts))
        self.assertIn("outsole", prompts[0])

    def test_custom_preset_is_limited_to_six(self):
        prompts = build_prompts("运动包", "custom", ["scene"] * 10)
        self.assertEqual(len(prompts), 6)


if __name__ == "__main__":
    unittest.main()
