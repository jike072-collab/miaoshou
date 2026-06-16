import tempfile
import unittest
from pathlib import Path

from lib.database import Database


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(Path(tempfile.mkdtemp()) / "test.db")

    def test_candidate_import_is_idempotent(self):
        url = "https://detail.1688.com/offer/123456.html"
        first = self.db.import_candidates([url])
        second = self.db.import_candidates([url])
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(len(self.db.list_candidates()), 1)
        self.assertEqual(first[0]["source_product_id"], "123456")

    def test_candidate_import_reads_offer_id_query_param(self):
        item = self.db.import_candidates([
            "https://detail.m.1688.com/page/index.html?offerId=987654321&skuId=1"
        ])[0]
        self.assertEqual(item["source_product_id"], "987654321")

    def test_product_round_trip(self):
        product = self.db.save_product({
            "title": "运动鞋", "sourceUrl": "https://example.com/p",
            "images": ["https://example.com/a.jpg"], "mainImage": "https://example.com/a.jpg",
            "weightG": 800,
        })
        self.assertEqual(product["title"], "运动鞋")
        self.assertEqual(product["weightG"], 800)
        self.assertEqual(product["images"], ["https://example.com/a.jpg"])

    def test_run_context_can_persist_phase_changes(self):
        run = self.db.create_run("publish", ["准备"], batch_id="batch", context={"phase": "prepare"})
        updated = self.db.update_run(run["id"], context={"phase": "confirm", "confirmedBy": "user"})
        self.assertEqual(updated["context"], {"phase": "confirm", "confirmedBy": "user"})


if __name__ == "__main__":
    unittest.main()
