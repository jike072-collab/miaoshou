import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from lib.automation import AutomationEngine, extension_id_from_public_key, local_urlopen
from lib.database import Database


class AutomationTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.db = Database(self.root / "test.db")
        self.engine = AutomationEngine(self.db, self.root)

    def test_keyword_search_waits_for_real_browser_in_dry_run(self):
        run = self.engine.create_keyword_search_run("运动鞋", "https://s.1688.com/example")
        updated = self.engine.run(run["id"])
        self.assertEqual(updated["status"], "waiting_browser")
        self.assertEqual(updated["context"]["keyword"], "运动鞋")

    def test_dry_publish_requires_then_completes_confirmation(self):
        now = 1
        self.db.execute(
            "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("batch", "test", "draft", 1, "[]", "[]", "{}", now, now),
        )
        run = self.engine.create_publish_run("batch")
        prepared = self.engine.run(run["id"])
        self.assertEqual(prepared["status"], "waiting_confirmation")
        completed = self.engine.confirm_publish(run["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertIn("未点击妙手最终发布", completed["current_step"])

    def test_resolve_chrome_path_can_find_running_translocated_app(self):
        path = self.root / "AppTranslocation/ABC/d/Google Chrome.app/Contents/MacOS/Google Chrome"
        path.parent.mkdir(parents=True)
        path.write_text("chrome")
        self.db.set_settings({"automation.chrome_path": "/missing/chrome"})
        output = str(path) + " --some-flag\n"
        with patch("lib.automation.subprocess.run") as run:
            run.return_value.stdout = output
            self.assertEqual(self.engine.resolve_chrome_path(), path)

    def test_plugin_extension_id_can_be_derived_from_manifest_key(self):
        key = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAm0xvIIHKojAuKi6hDzSXk08CoaaVVcZohhhKYVw/n/unXFnPxztMonajOC2lGe/nRqJjjLmkjc5cEpaQzimEYYgt5z9RYWp0wBYmec2RzHalGVOcUSswm4v4wgF1mWuN5q35fh3WYCdSVOVF5IXu8apCbteLGoMBn+ixzzRDsWSxZE4hZDnEzu7iX285SNAYje9ChPPVZuVDGqMwRFOc/rPPFe+Rndr6RgbS6WQkmf2iQ7A1XBL6U7qIz9OUUFHLPzIb8AD0wckoE17ylWOxseKICvdq+x3HYd+Ka1qSChaY9rIuDl0/sp0Za/c6mgmbu1oQzPAmez++tWPY5WIdlwIDAQAB"
        self.assertEqual(extension_id_from_public_key(key), "ecofkipcicjifkppbgnkaghcfofmpkia")

    def test_login_detection_rejects_1688_guest_homepage(self):
        pages = [{"url": "https://www.1688.com/", "text": "采购车\n登录后更多精彩\n立即登录"}]
        self.assertFalse(AutomationEngine.alibaba_logged_in(pages))

    def test_login_detection_accepts_1688_search_results(self):
        pages = [{
            "url": "https://s.1688.com/selloffer/offer_search.htm?keywords=%D4%CB%B6%AF%D0%AC",
            "text": "运动鞋 ¥ 29 已售1.4万+件 1件起购 晋江龙衍鞋业有限公司",
        }]
        self.assertTrue(AutomationEngine.alibaba_logged_in(pages))

    def test_local_cdp_requests_bypass_system_proxy(self):
        with patch("lib.automation.build_opener") as build:
            build.return_value.open.side_effect = RuntimeError("stop")
            with self.assertRaises(RuntimeError):
                local_urlopen("http://127.0.0.1:9222/json/version")
        self.assertTrue(build.called)

    def test_keyword_search_persists_image_count(self):
        run = self.engine.create_keyword_search_run("运动鞋", "https://s.1688.com/example")
        payload = {
            "ok": True,
            "events": [{"label": "写入待评估候选池", "status": "completed"}],
            "candidates": [{
                "url": "https://detail.1688.com/offer/123456.html",
                "title": "透气运动鞋",
                "image": "https://example.com/a.jpg",
                "sourceProductId": "123456",
                "category": "运动鞋",
                "sourcePrice": 29.5,
                "monthlySales": 14000,
                "dispatchHours": 72,
            }],
        }
        with patch("lib.automation.subprocess.run") as run_command:
            run_command.return_value.stdout = json.dumps(payload, ensure_ascii=False)
            result = self.engine._invoke_runner(run, {"kind": "keyword_search"})

        candidate = self.db.list_candidates()[0]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(candidate["image_count"], 1)
        self.assertEqual(candidate["images"], ["https://example.com/a.jpg"])
        self.assertEqual(candidate["source_product_id"], "123456")
        self.assertEqual(candidate["category"], "运动鞋")
        self.assertEqual(candidate["source_price"], 29.5)
        self.assertEqual(candidate["monthly_sales"], 14000)
        self.assertEqual(candidate["dispatch_hours"], 72)

    def test_failed_collection_persists_structured_diagnostics(self):
        candidate = self.db.import_candidates(["https://detail.1688.com/offer/123456.html"])[0]
        run = self.engine.create_collection_run(candidate)
        response = {
            "ok": False,
            "error": "插件按钮未找到",
            "failedStep": "调用妙手插件采集",
            "currentUrl": "https://detail.1688.com/offer/123456.html",
            "screenshot": "/tmp/collect-failed.png",
            "clickableText": ["采集", "加入采购车", "联系供应商"],
        }
        with patch("lib.automation.subprocess.run") as run_command:
            run_command.return_value.stdout = json.dumps(response, ensure_ascii=False)
            result = self.engine._invoke_runner(run, {"kind": "collection"})

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["current_step"], "调用妙手插件采集")
        self.assertEqual(result["screenshot"], "/tmp/collect-failed.png")
        self.assertEqual(result["diagnostics"]["failedStep"], "调用妙手插件采集")
        self.assertEqual(result["diagnostics"]["currentUrl"], "https://detail.1688.com/offer/123456.html")
        self.assertIn("插件", "；".join(result["diagnostics"]["suggestedActions"]))
        self.assertIn("采集", result["diagnostics"]["clickableText"])


if __name__ == "__main__":
    unittest.main()
