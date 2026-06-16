import tempfile
import unittest
from pathlib import Path

import app
from lib.database import Database


class CandidateDedupeTest(unittest.TestCase):
    def setUp(self):
        self.original_db = app.DB
        self.root = Path(tempfile.mkdtemp())
        app.DB = Database(self.root / "test.db")

    def tearDown(self):
        app.DB = self.original_db

    def create_candidate(self, url, **updates):
        candidate = app.DB.import_candidates([url])[0]
        if updates:
            candidate = app.DB.update_candidate(candidate["id"], updates)
        return candidate

    def test_duplicate_offer_id_is_skipped(self):
        self.create_candidate(
            "https://detail.1688.com/offer/100001.html",
            title="夏季透气运动鞋",
            images=["https://img.example.com/a.jpg"],
        )
        duplicate = self.create_candidate(
            "https://detail.m.1688.com/page/index.html?offerId=100001",
            title="夏季透气运动鞋升级款",
            images=["https://img.example.com/b.jpg"],
        )

        result = app.dedupe_candidates([duplicate["id"]])

        self.assertEqual(result["skipped"][0]["dedupeStatus"], "duplicate_offer_id")
        self.assertTrue(app.candidate_summary(app.DB.get_candidate(duplicate["id"]))["duplicateSkipped"])

    def test_collection_box_record_blocks_repeat_collection(self):
        candidate = self.create_candidate(
            "https://detail.1688.com/offer/200001.html",
            title="夏季防滑凉鞋",
            images=["https://img.example.com/sandal.jpg"],
        )
        app.DB.save_collection_box_record({
            "candidate_id": "old-candidate",
            "offer_id": "200001",
            "source_url": candidate["source_url"],
            "clean_title": "Summer Non Slip Sandals",
            "image_status": "image_ready",
            "miaoshou_status": "collected_to_box",
        })

        result = app.dedupe_candidates([candidate["id"]])

        self.assertEqual(result["skipped"][0]["dedupeStatus"], "already_collected_to_box")
        self.assertIn("采集箱", result["skipped"][0]["dedupeReason"])

    def test_duplicate_image_is_skipped_without_interrupting_new_candidate(self):
        self.create_candidate(
            "https://detail.1688.com/offer/300001.html",
            title="轻便运动包",
            images=["https://img.example.com/bag_800x800.jpg"],
        )
        duplicate = self.create_candidate(
            "https://detail.1688.com/offer/300002.html",
            title="轻便旅行包",
            images=["https://img.example.com/bag_400x400.jpg"],
        )
        new_candidate = self.create_candidate(
            "https://detail.1688.com/offer/300003.html",
            title="透气跑步鞋",
            images=["https://img.example.com/shoe.jpg"],
        )

        result = app.dedupe_candidates([duplicate["id"], new_candidate["id"]])
        statuses = {item["id"]: item["dedupeStatus"] for item in result["items"]}

        self.assertEqual(statuses[duplicate["id"]], "duplicate_image")
        self.assertEqual(statuses[new_candidate["id"]], "new_candidate")


if __name__ == "__main__":
    unittest.main()
