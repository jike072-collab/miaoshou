import tempfile
import time
import unittest
import uuid
from pathlib import Path

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

    def test_complete_batch_passes_and_reserves_idempotency_key(self):
        batch = self.make_batch("batch-1")
        self.assertEqual(app.validate_batch(batch), [])
        self.assertEqual(app.reserve_publish_keys(batch), [])
        keys = self.db.rows("SELECT * FROM publish_keys")
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0]["status"], "reserved")

    def test_published_product_blocks_other_batch(self):
        first = self.make_batch("batch-1")
        app.reserve_publish_keys(first)
        self.db.execute("UPDATE publish_keys SET status='published'")
        duplicates = app.reserve_publish_keys(self.make_batch("batch-2"))
        self.assertEqual(len(duplicates), 1)

    def test_hard_block_cannot_be_manually_unchecked(self):
        self.db.execute(
            "UPDATE market_versions SET blocked=1,block_reasons='[\"侵权风险\"]' WHERE product_id=? AND market='MY'",
            (self.product["id"],),
        )
        result = self.db.save_market_version(self.product["id"], "MY", {"blocked": False})
        self.assertTrue(result["blocked"])


if __name__ == "__main__":
    unittest.main()
