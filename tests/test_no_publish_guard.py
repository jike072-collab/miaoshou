import tempfile
import unittest
from pathlib import Path

from lib.local_config import (
    assert_publish_allowed,
    assert_real_pipeline_safety,
    assert_safe_collection_action,
    load_config,
    save_config,
)


class NoPublishGuardTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_publish_texts_are_blocked_when_no_publish_is_enabled(self):
        config = load_config(self.root)
        dangerous = ("publish", "submit", "confirm publish", "发布", "上架", "提交", "确认发布")

        for text in dangerous:
            with self.subTest(text=text):
                with self.assertRaisesRegex(RuntimeError, "no_publish=true"):
                    assert_safe_collection_action(config, "加入采集箱 " + text, "真实妙手采集")

    def test_publish_recipe_is_blocked_by_default(self):
        config = load_config(self.root)

        with self.assertRaisesRegex(RuntimeError, "no_publish=true"):
            assert_publish_allowed(config, [{"type": "clickText", "text": "最终发布"}], "最终发布")

    def test_real_pipeline_requires_no_publish_and_small_batch_limits(self):
        config = load_config(self.root)

        self.assertTrue(assert_real_pipeline_safety(config))

        with self.assertRaisesRegex(RuntimeError, "no_publish=true"):
            assert_real_pipeline_safety({**config, "no_publish": False})

        clamped = save_config(self.root, {**config, "max_items_per_run": 99, "max_pages_per_keyword": 9})
        self.assertEqual(clamped["max_items_per_run"], 10)
        self.assertEqual(clamped["max_pages_per_keyword"], 2)
        self.assertTrue(assert_real_pipeline_safety(clamped))


if __name__ == "__main__":
    unittest.main()
