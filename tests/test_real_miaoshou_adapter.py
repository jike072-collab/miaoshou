import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.database import Database
from lib.local_config import save_config
from lib.real_miaoshou_adapter import RealMiaoshouAdapter, detect_dangerous_texts


class FakeEngine:
    def __init__(self, pages):
        self.pages = pages

    def cdp_probe(self, port):
        return {"pages": self.pages}


class FakeBrowser:
    def __init__(self, pages=None, cdp_ready=True):
        self.pages = pages or []
        self.engine = FakeEngine(self.pages)
        self.cdp_ready = cdp_ready

    def debug_port(self):
        return 9222

    def start(self, pages=None, ensure_pages=False):
        return {
            "chrome_ready": True,
            "cdp_ready": self.cdp_ready,
            "profile_dir": "data/chrome-profile",
            "debug_port": 9222,
            "current_url": self.pages[0]["url"] if self.pages else "",
            "error": None,
        }

    def platform_status(self):
        return {
            "cdp_ready": self.cdp_ready,
            "waiting_for_manual": False,
            "requires_manual": False,
            "miaoshou_logged_in": True,
            "current_url": self.pages[0]["url"] if self.pages else "",
            "pages": [{"title": item.get("title", ""), "url": item.get("url", "")} for item in self.pages],
        }

    def screenshot(self, path=None):
        return "/tmp/miaoshou-diagnostic.png"


class RealMiaoshouAdapterTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.db = Database(self.root / "test.db")
        save_config(self.root, {
            "mode": "real",
            "dry_run_collect": True,
            "collect_to_box_only": True,
            "no_publish": True,
            "enable_miaoshou_collect": True,
        })
        self.pages = [{
            "url": "https://erp.91miaoshou.com/home",
            "title": "妙手",
            "text": "首页\n产品\n订单\n采集箱\n加入采集箱\n保存草稿\n最终发布",
        }]
        self.browser = FakeBrowser(self.pages)
        self.adapter = RealMiaoshouAdapter(self.db, self.root, self.browser)

    def ready_candidate(self, url="https://detail.1688.com/offer/123456.html"):
        candidate = self.db.import_candidates([url])[0]
        return self.db.update_candidate(candidate["id"], {
            "title": "夏季透气运动鞋",
            "clean_title": "Breathable Summer Sports Shoes",
            "source_product_id": "123456",
            "category": "运动鞋",
            "source_price": 30,
            "weight_g": 500,
            "monthly_sales": 1200,
            "rating": 4.8,
            "dispatch_hours": 24,
            "image_count": 3,
            "images": ["https://example.com/a.jpg", "https://example.com/b.jpg", "https://example.com/c.jpg"],
            "local_images": ["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.jpg"],
            "image_status": "image_ready",
            "sku_complete": True,
            "dedupe_checked_at": 1,
            "precheck_status": "precheck_passed",
            "precheck_reason": "通过预检",
        })

    def test_detect_dangerous_texts_flags_publish_actions(self):
        dangerous = detect_dangerous_texts(["加入采集箱", "确认发布", "保存草稿"])

        self.assertEqual(dangerous, ["确认发布"])

    def test_validate_candidate_blocks_duplicates_and_missing_requirements(self):
        candidate = self.ready_candidate()
        self.db.update_candidate(candidate["id"], {"dedupe_status": "duplicate_offer_id", "dedupe_reason": "重复"})

        valid, reasons = self.adapter.validate_candidate(self.db.get_candidate(candidate["id"]))

        self.assertFalse(valid)
        self.assertTrue(any("重复候选" in reason for reason in reasons))

    def test_collect_waits_for_manual_on_verification(self):
        candidate = self.ready_candidate()
        self.browser.pages = [{
            "url": "https://erp.91miaoshou.com/verify",
            "title": "短信验证",
            "text": "请完成短信验证",
        }]
        self.browser.engine.pages = self.browser.pages
        run = self.adapter.create_run(candidate, status="running")

        result = self.adapter.collect_candidate(candidate, run=run)

        self.assertEqual(result["status"], "waiting_for_manual")
        self.assertIn("验证", result["error"])
        self.assertEqual(result["diagnostics"]["failedStep"], "检查妙手登录态")
        self.assertIn("手动完成验证", "；".join(result["diagnostics"]["suggestedActions"]))

    def test_collect_blocks_dangerous_safe_recipe(self):
        candidate = self.ready_candidate()
        self.browser.pages = [{
            "url": "https://erp.91miaoshou.com/home",
            "title": "妙手",
            "text": "首页\n产品\n订单\n采集箱\n加入采集箱\n保存草稿",
        }]
        self.browser.engine.pages = self.browser.pages
        self.db.set_settings({"automation.miaoshou_box_recipe": [{"type": "clickText", "text": "确认发布"}]})
        run = self.adapter.create_run(candidate, status="running")

        result = self.adapter.collect_candidate(candidate, run=run)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("no_publish=true", result["error"])
        self.assertEqual(result["diagnostics"]["failedStep"], "检查安全开关")

    def test_collect_success_writes_collection_box_record(self):
        candidate = self.ready_candidate()
        self.browser.pages = [{
            "url": "https://erp.91miaoshou.com/home",
            "title": "妙手",
            "text": "首页\n产品\n订单\n采集箱\n加入采集箱\n保存草稿",
        }]
        self.browser.engine.pages = self.browser.pages
        self.db.set_settings({"automation.miaoshou_box_recipe": [{"type": "clickText", "text": "加入采集箱"}]})
        run = self.adapter.create_run(candidate, status="running", context={"markets": ["MY"]})

        with patch.object(self.adapter, "invoke_safe_recipe", return_value={"ok": True, "events": [{"label": "加入采集箱", "status": "completed"}]}):
            result = self.adapter.collect_candidate(candidate, run=run)

        records = self.db.list_collection_box_records()
        refreshed = self.db.get_candidate(candidate["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(records[0]["candidate_id"], candidate["id"])
        self.assertEqual(records[0]["clean_title"], "Breathable Summer Sports Shoes")
        self.assertEqual(records[0]["images_used"], ["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.jpg"])
        self.assertEqual(refreshed["status"], "collected_to_box")
        self.assertTrue(refreshed["collected_at"])
        self.assertEqual(result["diagnostics"]["dangerousText"], [])

    def test_collect_pauses_when_page_contains_publish_buttons(self):
        candidate = self.ready_candidate()
        self.db.set_settings({"automation.miaoshou_box_recipe": [{"type": "clickText", "text": "加入采集箱"}]})
        run = self.adapter.create_run(candidate, status="running", context={"markets": ["MY"]})

        result = self.adapter.collect_candidate(candidate, run=run)

        self.assertEqual(result["status"], "waiting_for_manual")
        self.assertEqual(result["diagnostics"]["failedStep"], "扫描危险发布按钮")
        self.assertIn("危险按钮", result["error"])
        self.assertIn("最终发布", result["diagnostics"]["dangerousText"])

    def test_collect_ready_reports_blocked_candidates(self):
        candidate = self.ready_candidate()
        self.db.update_candidate(candidate["id"], {"image_status": "needs_generation", "image_reason": "图片数量不足"})

        result = self.adapter.collect_ready([candidate["id"]])

        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["blocked"]), 1)
        self.assertIn("图片未就绪", result["blocked"][0]["error"])


if __name__ == "__main__":
    unittest.main()
