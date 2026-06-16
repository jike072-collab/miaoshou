"""Chrome/CDP manager for the local Miaoshou workbench."""

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request

from lib.automation import AutomationEngine, local_urlopen
from lib.local_config import config_status, load_config


VERIFICATION_MARKERS = (
    "验证码", "短信验证", "人机验证", "滑块", "拖动滑块", "安全验证", "请按照说明进行验证",
    "请完成验证", "验证后继续", "身份验证", "风险验证", "captcha", "verify", "verification",
    "robot", "security check",
)

ALIBABA_LOGIN_MARKERS = ("采购车", "我的阿里", "收藏的品", "关注的店", "已售", "供应商", "店铺")
ALIBABA_LOGOUT_MARKERS = ("立即登录", "登录后更多精彩", "请登录", "账号登录")
MIAOSHOU_LOGIN_MARKERS = ("首页", "产品", "订单", "采集箱", "刊登", "店铺")
MIAOSHOU_LOGOUT_MARKERS = ("登录", "手机号", "密码", "验证码登录", "忘记密码")


class BrowserManager:
    def __init__(self, database, data_dir):
        self.db = database
        self.data_dir = Path(data_dir)
        self.engine = AutomationEngine(database, data_dir)
        self.process = None
        self.last_error = None

    def local_config(self):
        return load_config(self.data_dir)

    def debug_port(self):
        return int(self.local_config().get("chrome_debug_port") or self.db.setting("automation.cdp_port", 9222) or 9222)

    def profile_dir(self):
        return self.engine.chrome_profile_dir()

    def chrome_path(self):
        return self.engine.resolve_chrome_path()

    def cdp_json(self, path, timeout=2):
        return json.loads(local_urlopen("http://127.0.0.1:%s%s" % (self.debug_port(), path), timeout=timeout).read().decode())

    def cdp_ready(self):
        try:
            payload = self.cdp_json("/json/version", timeout=1)
            return bool(payload.get("webSocketDebuggerUrl"))
        except (URLError, OSError, json.JSONDecodeError):
            return False

    def targets(self):
        try:
            return self.cdp_json("/json/list", timeout=2)
        except (URLError, OSError, json.JSONDecodeError):
            return []

    def current_url(self):
        pages = [item for item in self.targets() if item.get("type") == "page"]
        if not pages:
            return ""
        active = next((item for item in pages if item.get("url") and not item.get("url", "").startswith("devtools://")), pages[0])
        return active.get("url") or ""

    def status(self):
        chrome = self.chrome_path()
        error = self.last_error
        if not chrome.is_file():
            error = "未找到 Google Chrome"
        cdp_ready = self.cdp_ready()
        return {
            "chrome_ready": chrome.is_file(),
            "cdp_ready": cdp_ready,
            "profile_dir": str(self.profile_dir()),
            "debug_port": self.debug_port(),
            "current_url": self.current_url() if cdp_ready else "",
            "error": error,
        }

    def start_pages(self):
        return [
            self.db.setting("automation.miaoshou_url", "https://erp.91miaoshou.com/"),
            self.db.setting("automation.alibaba_url", "https://www.1688.com/"),
        ]

    def ensure_tabs(self, pages):
        targets = self.targets()
        for url in pages:
            hostname = (urlparse(url).hostname or "").removeprefix("www.")
            has_target = any(hostname and hostname in (item.get("url") or "") for item in targets)
            if not has_target:
                self.open_tab(url)

    def start_alibaba(self):
        return self.start(
            pages=[self.db.setting("automation.alibaba_url", "https://www.1688.com/")],
            ensure_pages=True,
        )

    def start(self, pages=None, ensure_pages=False):
        pages = [str(url).strip() for url in (pages or self.start_pages()) if str(url).strip()]
        if self.cdp_ready():
            self.last_error = None
            if ensure_pages:
                self.ensure_tabs(pages)
            return self.status()
        chrome = self.chrome_path()
        if not chrome.is_file():
            self.last_error = "未找到 Google Chrome，请先安装并在设置中填写路径"
            return self.status()
        profile = self.profile_dir()
        profile.mkdir(parents=True, exist_ok=True)
        port = str(self.debug_port())
        try:
            self.process = subprocess.Popen([
                str(chrome),
                "--remote-debugging-port=" + port,
                "--user-data-dir=" + str(profile),
                "--no-first-run",
                "--no-default-browser-check",
                *pages,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            for url in pages:
                self.open_tab(url)
            self.last_error = None
        except OSError as exc:
            self.last_error = str(exc)
        return self.status()

    def stop(self):
        stopped = False
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            stopped = True
        else:
            stopped = self.stop_by_profile()
        self.process = None
        if stopped:
            self.last_error = None
        return self.status()

    def stop_by_profile(self):
        profile = str(self.profile_dir())
        stopped = False
        try:
            result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=3)
            for line in result.stdout.splitlines():
                if "--user-data-dir=" + profile not in line:
                    continue
                pid = int(line.strip().split(None, 1)[0])
                try:
                    if pid != os.getpid():
                        os.kill(pid, signal.SIGTERM)
                        stopped = True
                except OSError:
                    pass
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return stopped

    def restart(self):
        self.stop()
        return self.start()

    def open_tab(self, url):
        endpoint = "http://127.0.0.1:%s/json/new?%s" % (self.debug_port(), quote(url, safe=""))
        try:
            local_urlopen(Request(endpoint, method="PUT"), timeout=2).read()
        except (URLError, OSError):
            try:
                local_urlopen(endpoint, timeout=2).read()
            except (URLError, OSError):
                self.last_error = "无法打开 Chrome 新标签页"
        return self.status()

    def screenshot(self, path=None):
        path = Path(path or (self.data_dir / "screenshots" / ("browser-%s.png" % int(time.time()))))
        path.parent.mkdir(parents=True, exist_ok=True)
        node_path = self.db.setting("automation.node_path", "node")
        script = Path(__file__).resolve().parent.parent / "scripts" / "cdp_screenshot.mjs"
        result = subprocess.run([node_path, str(script), str(self.debug_port()), str(path)], capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            self.last_error = result.stderr.strip() or result.stdout.strip() or "截图失败"
            raise RuntimeError(self.last_error)
        return str(path)

    def platform_status(self):
        browser = self.status()
        pages = self.engine.cdp_probe(self.debug_port()).get("pages") if browser["cdp_ready"] else []
        pages = pages or []
        verification = detect_verification(pages)
        alibaba = detect_alibaba_login(pages)
        miaoshou = detect_miaoshou_login(pages)
        requires_manual = bool(verification["detected"] or alibaba["needs_login"] or miaoshou["needs_login"] or not browser["cdp_ready"])
        state = "waiting_for_manual" if requires_manual else "ready"
        return {
            **browser,
            "status": state,
            "waiting_for_manual": state == "waiting_for_manual",
            "requires_manual": requires_manual,
            "manual_message": manual_message(browser, alibaba, miaoshou, verification),
            "alibaba_logged_in": alibaba["logged_in"],
            "miaoshou_logged_in": miaoshou["logged_in"],
            "verification_required": verification["detected"],
            "verification_type": verification["type"],
            "verification_pages": verification["pages"],
            "pages": [{"title": item.get("title", ""), "url": item.get("url", "")} for item in pages],
            "safety": config_status(self.local_config()),
            "error": browser.get("error"),
        }


def page_text(page):
    return ("%s\n%s\n%s" % (page.get("title", ""), page.get("url", ""), page.get("text", ""))).lower()


def detect_verification(pages):
    matches = []
    matched_texts = []
    for page in pages:
        text = page_text(page)
        if any(marker.lower() in text for marker in VERIFICATION_MARKERS):
            matches.append({"title": page.get("title", ""), "url": page.get("url", "")})
            matched_texts.append(text)
    label = ""
    if matches:
        sample = matched_texts[0]
        if "短信" in sample:
            label = "sms"
        elif "验证码" in sample or "captcha" in sample:
            label = "captcha"
        else:
            label = "human_verification"
    return {"detected": bool(matches), "type": label, "pages": matches}


def detect_alibaba_login(pages):
    relevant = [page for page in pages if "1688.com" in (page.get("url") or "")]
    logged_in = False
    needs_login = not relevant
    for page in relevant:
        text = page_text(page)
        if any(marker.lower() in text for marker in ALIBABA_LOGOUT_MARKERS):
            needs_login = True
        if any(marker.lower() in text for marker in ALIBABA_LOGIN_MARKERS):
            logged_in = True
            needs_login = False
    return {"logged_in": logged_in, "needs_login": needs_login}


def detect_miaoshou_login(pages):
    relevant = [page for page in pages if "91miaoshou.com" in (page.get("url") or "")]
    logged_in = False
    needs_login = not relevant
    for page in relevant:
        text = page_text(page)
        login_like = "login" in (page.get("url") or "").lower() or any(marker.lower() in text for marker in MIAOSHOU_LOGOUT_MARKERS)
        app_like = any(marker.lower() in text for marker in MIAOSHOU_LOGIN_MARKERS)
        if login_like and not app_like:
            needs_login = True
        if app_like and "login" not in (page.get("url") or "").lower():
            logged_in = True
            needs_login = False
    return {"logged_in": logged_in, "needs_login": needs_login}


def manual_message(browser, alibaba, miaoshou, verification):
    if not browser.get("cdp_ready"):
        return "请先启动专用 Chrome，并保持调试端口连接。"
    if verification.get("detected"):
        return "检测到验证码/人机/短信验证，请在 Chrome 中手动完成后重新检测。"
    if alibaba.get("needs_login") or miaoshou.get("needs_login"):
        return "请在专用 Chrome 中手动完成 1688 和妙手登录后重新检测。"
    return ""
