import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.browser_manager import (
    BrowserManager,
    detect_alibaba_login,
    detect_miaoshou_login,
    detect_verification,
    manual_message,
)
from lib.database import Database
from lib.local_config import save_config


class BrowserManagerTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.db = Database(self.root / "test.db")
        save_config(self.root, {
            "mode": "real",
            "dry_run_collect": True,
            "no_publish": True,
            "chrome_debug_port": 9333,
            "chrome_profile_dir": "data/chrome-profile",
        })
        self.manager = BrowserManager(self.db, self.root)

    def test_status_reports_configured_profile_and_debug_port(self):
        missing_chrome = self.root / "missing-chrome"
        with patch.object(self.manager, "chrome_path", return_value=missing_chrome), \
                patch.object(self.manager, "cdp_ready", return_value=False):
            status = self.manager.status()

        self.assertFalse(status["chrome_ready"])
        self.assertFalse(status["cdp_ready"])
        self.assertEqual(status["debug_port"], 9333)
        self.assertTrue(status["profile_dir"].endswith("chrome-profile"))
        self.assertEqual(status["current_url"], "")
        self.assertIn("未找到", status["error"])

    def test_start_alibaba_only_ensures_1688_tab_when_cdp_is_ready(self):
        opened = []
        with patch.object(self.manager, "cdp_ready", return_value=True), \
                patch.object(self.manager, "targets", return_value=[]), \
                patch.object(self.manager, "open_tab", side_effect=lambda url: opened.append(url)), \
                patch.object(self.manager, "status", return_value={"cdp_ready": True}):
            status = self.manager.start_alibaba()

        self.assertEqual(status["cdp_ready"], True)
        self.assertEqual(opened, ["https://www.1688.com/"])

    def test_platform_status_waits_for_manual_when_cdp_is_not_ready(self):
        with patch.object(self.manager, "status", return_value={
            "chrome_ready": True,
            "cdp_ready": False,
            "profile_dir": str(self.root / "chrome-profile"),
            "debug_port": 9333,
            "current_url": "",
            "error": None,
        }):
            status = self.manager.platform_status()

        self.assertEqual(status["status"], "waiting_for_manual")
        self.assertTrue(status["waiting_for_manual"])
        self.assertFalse(status["alibaba_logged_in"])
        self.assertFalse(status["miaoshou_logged_in"])
        self.assertIn("启动专用 Chrome", status["manual_message"])
        self.assertTrue(status["safety"]["publishForbidden"])

    def test_platform_status_waits_for_manual_on_verification(self):
        pages = [
            {"url": "https://www.1688.com/", "title": "安全验证", "text": "请完成验证码后继续"},
            {"url": "https://erp.91miaoshou.com/home", "title": "妙手", "text": "首页 产品 订单 采集箱"},
        ]
        with patch.object(self.manager, "status", return_value={
            "chrome_ready": True,
            "cdp_ready": True,
            "profile_dir": str(self.root / "chrome-profile"),
            "debug_port": 9333,
            "current_url": "https://www.1688.com/",
            "error": None,
        }), patch.object(self.manager.engine, "cdp_probe", return_value={"pages": pages}):
            status = self.manager.platform_status()

        self.assertTrue(status["verification_required"])
        self.assertEqual(status["verification_type"], "captcha")
        self.assertTrue(status["waiting_for_manual"])
        self.assertIn("手动完成", status["manual_message"])

    def test_platform_status_ready_when_both_platforms_logged_in(self):
        pages = [
            {"url": "https://s.1688.com/selloffer/offer_search.htm", "title": "1688", "text": "运动鞋 已售 供应商 店铺"},
            {"url": "https://erp.91miaoshou.com/home", "title": "妙手", "text": "首页 产品 订单 采集箱"},
        ]
        with patch.object(self.manager, "status", return_value={
            "chrome_ready": True,
            "cdp_ready": True,
            "profile_dir": str(self.root / "chrome-profile"),
            "debug_port": 9333,
            "current_url": "https://erp.91miaoshou.com/home",
            "error": None,
        }), patch.object(self.manager.engine, "cdp_probe", return_value={"pages": pages}):
            status = self.manager.platform_status()

        self.assertEqual(status["status"], "ready")
        self.assertFalse(status["waiting_for_manual"])
        self.assertTrue(status["alibaba_logged_in"])
        self.assertTrue(status["miaoshou_logged_in"])
        self.assertFalse(status["verification_required"])

    def test_detection_helpers_classify_login_and_verification(self):
        verification = detect_verification([
            {"url": "https://example.com", "title": "短信验证", "text": "请完成短信验证"},
        ])
        alibaba = detect_alibaba_login([
            {"url": "https://www.1688.com/", "title": "1688", "text": "采购车 我的阿里 收藏的品"},
        ])
        miaoshou = detect_miaoshou_login([
            {"url": "https://erp.91miaoshou.com/home", "title": "妙手", "text": "首页 产品 订单 采集箱"},
        ])

        self.assertTrue(verification["detected"])
        self.assertEqual(verification["type"], "sms")
        self.assertTrue(alibaba["logged_in"])
        self.assertFalse(alibaba["needs_login"])
        self.assertTrue(miaoshou["logged_in"])
        self.assertFalse(miaoshou["needs_login"])

    def test_manual_message_never_suggests_bypassing_verification(self):
        message = manual_message(
            {"cdp_ready": True},
            {"needs_login": False},
            {"needs_login": False},
            {"detected": True},
        )

        self.assertIn("手动完成", message)
        self.assertNotIn("绕过", message)


if __name__ == "__main__":
    unittest.main()
