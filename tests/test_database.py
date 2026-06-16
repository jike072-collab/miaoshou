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

    def test_candidate_can_store_real_1688_search_fields(self):
        item = self.db.import_candidates(["https://detail.1688.com/offer/123456.html"], keyword="运动鞋")[0]
        updated = self.db.update_candidate(item["id"], {
            "min_order": 2,
            "sales_text": "已售 3000 件",
            "supplier_name": "晋江鞋业",
            "shop_url": "https://shop.1688.com/",
            "origin_place": "福建泉州",
            "search_page": 1,
            "search_rank": 8,
        })

        self.assertEqual(updated["min_order"], 2)
        self.assertEqual(updated["sales_text"], "已售 3000 件")
        self.assertEqual(updated["supplier_name"], "晋江鞋业")
        self.assertEqual(updated["shop_url"], "https://shop.1688.com/")
        self.assertEqual(updated["origin_place"], "福建泉州")
        self.assertEqual(updated["search_page"], 1)
        self.assertEqual(updated["search_rank"], 8)

    def test_collection_box_record_round_trip(self):
        candidate = self.db.import_candidates(["https://detail.1688.com/offer/123456.html"])[0]
        record = self.db.save_collection_box_record({
            "candidate_id": candidate["id"],
            "offer_id": "123456",
            "source_url": candidate["source_url"],
            "clean_title": "透气运动鞋",
            "image_status": "approved",
            "images_used": ["/tmp/a.jpg", "/tmp/b.jpg"],
            "miaoshou_status": "采集箱",
            "run_id": "run-1",
        })

        records = self.db.list_collection_box_records()
        self.assertEqual(record["candidate_id"], candidate["id"])
        self.assertEqual(record["offer_id"], "123456")
        self.assertEqual(record["miaoshou_status"], "采集箱")
        self.assertEqual(record["images_used"], ["/tmp/a.jpg", "/tmp/b.jpg"])
        self.assertEqual(records[0]["id"], record["id"])

    def test_candidate_can_store_precheck_fields(self):
        candidate = self.db.import_candidates(["https://detail.1688.com/offer/123456.html"])[0]
        updated = self.db.update_candidate(candidate["id"], {
            "precheck_status": "precheck_passed",
            "precheck_reason": "通过预检",
            "precheck_reasons": ["通过预检"],
            "precheck_details": {"seaScore": 6, "missingBasicFields": []},
            "sea_fit_status": "sea_fit_good",
            "season_fit_status": "season_fit_good",
            "precheck_checked_at": 123,
        })

        self.assertEqual(updated["precheck_status"], "precheck_passed")
        self.assertEqual(updated["precheck_reasons"], ["通过预检"])
        self.assertEqual(updated["precheck_details"]["seaScore"], 6)
        self.assertEqual(updated["sea_fit_status"], "sea_fit_good")
        self.assertEqual(updated["season_fit_status"], "season_fit_good")

    def test_candidate_can_store_title_cleaning_fields_and_records(self):
        candidate = self.db.import_candidates(["https://detail.1688.com/offer/123456.html"])[0]
        updated = self.db.update_candidate(candidate["id"], {
            "clean_title": "Breathable Summer Sports Shoes",
            "title_clean_removed_terms": ["跨境", "外贸"],
            "title_clean_risk_terms": ["高仿"],
            "title_cleaned_at": 123,
        })
        record = self.db.save_title_cleaning_record({
            "candidate_id": candidate["id"],
            "original_title": "跨境外贸高仿运动鞋",
            "clean_title": "Sports Shoes",
            "removed_terms": ["跨境", "外贸"],
            "risk_terms": ["高仿"],
            "cleaned_at": 456,
        })

        records = self.db.list_title_cleaning_records(candidate["id"])
        self.assertEqual(updated["clean_title"], "Breathable Summer Sports Shoes")
        self.assertEqual(updated["title_clean_removed_terms"], ["跨境", "外贸"])
        self.assertEqual(updated["title_clean_risk_terms"], ["高仿"])
        self.assertEqual(record["risk_terms"], ["高仿"])
        self.assertEqual(records[0]["clean_title"], "Sports Shoes")

    def test_candidate_can_store_image_fields_and_records(self):
        candidate = self.db.import_candidates(["https://detail.1688.com/offer/123456.html"])[0]
        updated = self.db.update_candidate(candidate["id"], {
            "image_status": "image_ready",
            "image_reason": "原图可用",
            "image_reasons": [],
            "image_details": {"usableImages": 3, "ocrAvailable": False},
            "local_images": ["/tmp/a.jpg"],
            "image_checked_at": 123,
        })
        record = self.db.save_image_analysis_record({
            "candidate_id": candidate["id"],
            "source_url": candidate["source_url"],
            "local_path": "/tmp/a.jpg",
            "status": "image_ready",
            "reasons": [],
            "details": {"usableImages": 3},
            "checked_at": 456,
        })

        records = self.db.list_image_analysis_records(candidate["id"])
        self.assertEqual(updated["image_status"], "image_ready")
        self.assertEqual(updated["image_details"]["usableImages"], 3)
        self.assertEqual(updated["local_images"], ["/tmp/a.jpg"])
        self.assertEqual(record["details"]["usableImages"], 3)
        self.assertEqual(records[0]["status"], "image_ready")

    def test_candidate_title_change_invalidates_clean_title(self):
        candidate = self.db.import_candidates(["https://detail.1688.com/offer/123456.html"])[0]
        self.db.update_candidate(candidate["id"], {
            "clean_title": "Breathable Sports Shoes",
            "title_clean_removed_terms": ["跨境"],
            "title_cleaned_at": 123,
        })

        updated = self.db.update_candidate(candidate["id"], {"title": "新的运动鞋标题"})

        self.assertEqual(updated["clean_title"], "")
        self.assertEqual(updated["title_clean_removed_terms"], [])
        self.assertIsNone(updated["title_cleaned_at"])

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

    def test_automation_log_round_trip_and_resolution(self):
        run = self.db.create_run("pipeline", ["搜索"])
        log = self.db.save_automation_log({
            "run_id": run["id"],
            "sourcing_run_id": "source-1",
            "candidate_id": "candidate-1",
            "product": "透气运动鞋",
            "keyword": "运动鞋",
            "current_step": "图片检查",
            "status": "failed",
            "message": "图片未达标",
            "error": "图片含中文",
            "screenshot": "/tmp/shot.png",
            "current_url": "https://example.com",
            "details": {"suggestedActions": ["换图"]},
        })

        logs = self.db.list_automation_logs(run["id"])
        updated = self.db.update_automation_log(log["id"], resolution="handled")

        self.assertEqual(logs[0]["id"], log["id"])
        self.assertEqual(logs[0]["details"], {"suggestedActions": ["换图"]})
        self.assertEqual(logs[0]["current_step"], "图片检查")
        self.assertEqual(updated["resolution"], "handled")


if __name__ == "__main__":
    unittest.main()
