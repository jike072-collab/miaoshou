"""Safe automation state machine for Miaoshou collection and publishing."""

import base64
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener, urlopen

from lib.local_config import assert_publish_allowed, config_status, load_config


COLLECT_STEPS = [
    "检查Chrome与调试端口", "检查妙手登录态", "检查1688登录与授权",
    "打开1688商品页", "核对1688商品ID", "调用妙手插件采集",
    "核对插件成功提示", "打开妙手公用采集箱", "匹配来源商品", "认领到TikTok采集箱",
]

PUBLISH_STEPS = [
    "检查批次完整性", "检查图片审核", "检查五国价格与库存", "检查妙手登录态",
    "选择妙手账号与主体", "打开TikTok采集箱", "填写商品与规格", "上传审核图片",
    "关联目标店铺", "填写各站点价格仓库库存", "回读并差异校验", "等待人工确认",
]


def source_product_id(url):
    for pattern in (r"offer/(\d+)", r"offerId=(\d+)", r"id=(\d+)"):
        match = re.search(pattern, url or "")
        if match:
            return match.group(1)
    return ""


def extension_id_from_public_key(key):
    if not key:
        return ""
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(char, 16)) for char in digest)


def local_urlopen(url, timeout=2):
    opener = build_opener(ProxyHandler({}))
    return opener.open(url, timeout=timeout)


class AutomationEngine:
    def __init__(self, database, data_dir):
        self.db = database
        self.data_dir = Path(data_dir)
        self.profile_dir = self.data_dir / "chrome-profile"

    def resolve_chrome_path(self):
        configured = Path(str(self.db.setting("automation.chrome_path", ""))).expanduser()
        candidates = [
            configured,
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        try:
            result = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, timeout=3)
            for line in result.stdout.splitlines():
                marker = "/Google Chrome.app/Contents/MacOS/Google Chrome"
                if marker not in line:
                    continue
                candidate = Path(line[:line.index(marker) + len(marker)].strip())
                if candidate.is_file():
                    return candidate
        except (OSError, subprocess.SubprocessError):
            pass
        return configured

    def plugin_extension_id(self):
        configured = str(self.db.setting("automation.plugin_extension_id", "")).strip()
        if configured:
            return configured
        plugin_dir = Path(str(self.db.setting("automation.plugin_unpack_dir", ""))).expanduser()
        manifest = plugin_dir / "manifest.json"
        if not manifest.is_file():
            return ""
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            return extension_id_from_public_key(payload.get("key", ""))
        except (OSError, json.JSONDecodeError, ValueError):
            return ""

    def local_config(self):
        return load_config(self.data_dir)

    def chrome_profile_dir(self):
        value = str(self.local_config().get("chrome_profile_dir") or "data/chrome-profile")
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        if path.parts and path.parts[0] == "data":
            return self.data_dir.parent / path
        return self.data_dir / path

    def publish_guard_status(self):
        return config_status(self.local_config())

    def ensure_publish_allowed(self, recipe=None, context="发布动作"):
        return assert_publish_allowed(self.local_config(), recipe, context)

    def cdp_probe(self, port):
        node_path = self.db.setting("automation.node_path", "node")
        script = Path(__file__).resolve().parent.parent / "scripts" / "cdp_probe.mjs"
        try:
            result = subprocess.run(
                [node_path, str(script), str(port)], capture_output=True, text=True, timeout=8,
            )
            if result.returncode != 0:
                return {}
            return json.loads(result.stdout or "{}")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return {}

    @staticmethod
    def miaoshou_logged_in(pages):
        for page in pages:
            url = page.get("url", "")
            text = page.get("text", "")
            if "91miaoshou.com" not in url or "login" in url.lower():
                continue
            if "首页" in text and "产品" in text and "订单" in text:
                return True
        return False

    @staticmethod
    def alibaba_logged_in(pages):
        for page in pages:
            url = page.get("url", "")
            text = page.get("text", "")
            if "1688.com" not in url:
                continue
            if any(marker in text for marker in ("立即登录", "登录后更多精彩", "请登录")):
                return False
            if any(marker in text for marker in ("采购车", "我的阿里", "收藏的品", "关注的店")):
                return True
            if any(marker in url for marker in ("offer_search", "detail.1688.com", "page/index.html")) and all(
                marker in text for marker in ("¥", "起购")
            ) and any(marker in text for marker in ("已售", "全网", "供应商", "店铺")):
                return True
        return False

    @staticmethod
    def open_cdp_tab(port, url):
        try:
            local_urlopen("http://127.0.0.1:%s/json/new?%s" % (port, url), timeout=2).read()
        except (URLError, OSError):
            pass

    def preflight(self):
        chrome_path = self.resolve_chrome_path()
        plugin_dir = Path(str(self.db.setting("automation.plugin_unpack_dir", ""))).expanduser()
        port = int(self.db.setting("automation.cdp_port", 9222))
        plugin_id = self.plugin_extension_id()
        checks = {
            "chromeInstalled": chrome_path.is_file(),
            "chromePath": str(chrome_path),
            "chromeInstallStable": "AppTranslocation" not in str(chrome_path),
            "cdpConnected": False,
            "mode": self.db.setting("automation.mode", "dry_run"),
            "profileDir": str(self.chrome_profile_dir()),
            "pluginVerified": bool(self.db.setting("automation.plugin_verified", False)),
            "miaoshouLoginVerified": bool(self.db.setting("automation.miaoshou_login_verified", False)),
            "requiresCalibration": not bool(self.db.setting("automation.publish_recipe", [])),
            "pluginPackageReady": (plugin_dir / "manifest.json").is_file(),
            "pluginPackagePath": str(plugin_dir),
            "pluginExtensionId": plugin_id,
            "safety": self.publish_guard_status(),
        }
        try:
            payload = json.loads(local_urlopen("http://127.0.0.1:%s/json/version" % port, timeout=1).read().decode())
            checks["cdpConnected"] = bool(payload.get("webSocketDebuggerUrl"))
            checks["browser"] = payload.get("Browser", "")
            targets = json.loads(local_urlopen("http://127.0.0.1:%s/json/list" % port, timeout=2).read().decode())
            extension_targets = [item for item in targets if (item.get("url") or "").startswith("chrome-extension://")]
            checks["pluginVerified"] = any(
                (plugin_id and plugin_id in ((item.get("url") or "") + " " + (item.get("title") or "")))
                or "妙手" in (item.get("title") or "") or "跨境erp" in (item.get("title") or "").lower()
                for item in extension_targets
            )
            probe = self.cdp_probe(port)
            pages = probe.get("pages") or []
            checks["pluginVerified"] = checks["pluginVerified"] or any(
                any(marker in (page.get("text") or "") for marker in ("跨境ERP", "采集本页", "采集选中", "停用插件"))
                for page in pages
            )
            checks["miaoshouLoginVerified"] = self.miaoshou_logged_in(pages)
            checks["alibabaLoginVerified"] = self.alibaba_logged_in(pages)
        except (URLError, OSError, json.JSONDecodeError):
            pass
        return checks

    def launch_chrome(self):
        chrome_path = self.resolve_chrome_path()
        if not chrome_path.is_file():
            raise RuntimeError("未找到正版 Google Chrome，请先安装并在设置中填写路径")
        port = str(self.db.setting("automation.cdp_port", 9222))
        profile_dir = self.chrome_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)
        pages = [
            self.db.setting("automation.miaoshou_url", "https://erp.91miaoshou.com/"),
            self.db.setting("automation.alibaba_url", "https://www.1688.com/"),
        ]
        plugin_dir = Path(str(self.db.setting("automation.plugin_unpack_dir", ""))).expanduser()
        if (plugin_dir / "manifest.json").is_file():
            pages.insert(0, "chrome://extensions/")
        subprocess.Popen([
            str(chrome_path), "--remote-debugging-port=" + port,
            "--user-data-dir=" + str(profile_dir),
            "--no-first-run", "--no-default-browser-check",
            *pages,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        for url in pages:
            if not url.startswith("chrome://"):
                self.open_cdp_tab(port, url)
        return self.preflight()

    def create_collection_run(self, candidate):
        return self.db.create_run("collection", COLLECT_STEPS, candidate_id=candidate["id"])

    def create_publish_run(self, batch_id):
        return self.db.create_run("publish", PUBLISH_STEPS, batch_id=batch_id)

    def create_keyword_search_run(self, keyword, url):
        return self.db.create_run(
            "keyword_search", ["打开1688搜索页", "读取商品卡片", "写入待评估候选池"],
            context={"keyword": keyword, "url": url},
        )

    def is_dry_run(self, run):
        if run and run.get("kind") == "collection" and self.local_config().get("dry_run_collect", True):
            return True
        if self.db.setting("automation.mode", "dry_run") == "dry_run":
            return True
        if run and run.get("batch_id"):
            batch = self.db.row("SELECT dry_run FROM batches WHERE id=?", (run["batch_id"],))
            return bool(batch and batch["dry_run"])
        return False

    def execute_dry_run(self, run_id):
        run = self.db.get_run(run_id)
        steps = []
        for label in run["steps"]:
            steps.append({"label": label, "status": "completed" if label != "等待人工确认" else "waiting"})
        status = "waiting_confirmation" if run["kind"] == "publish" else "ready_for_live"
        return self.db.update_run(run_id, status=status, current_step=steps[-1]["label"], steps=steps)

    def execute_live(self, run_id, phase="prepare"):
        run = self.db.get_run(run_id)
        checks = self.preflight()
        if not checks["chromeInstalled"] or not checks["cdpConnected"]:
            return self.mark_failed(run, "blocked", "Chrome未连接，请启动专用Chrome", "检查Chrome与调试端口", checks=checks)
        if run["kind"] == "publish" and checks["requiresCalibration"]:
            return self.mark_failed(run, "blocked", "发布动作配方尚未配置，请先校准妙手页面。", "检查批次完整性", checks=checks)
        if run["kind"] == "publish":
            try:
                self.ensure_publish_allowed(self.db.setting("automation.publish_recipe", []), "真实发布流程")
            except RuntimeError as exc:
                return self.mark_failed(run, "blocked", str(exc), "no_publish 安全拦截", checks=checks)
        payload = {
            "kind": run["kind"], "port": int(self.db.setting("automation.cdp_port", 9222)),
            "miaoshouUrl": self.db.setting("automation.miaoshou_url", "https://erp.91miaoshou.com/"),
            "recipe": self.db.setting("automation.collection_recipe", []) if run["kind"] == "collection" else self.db.setting("automation.publish_recipe", []),
            "variables": {}, "phase": phase,
        }
        if run["candidate_id"]:
            candidate = self.db.get_candidate(run["candidate_id"])
            payload.update({
                "url": candidate["source_url"], "productId": candidate.get("source_product_id") or "",
                "collectTexts": self.db.setting("automation.plugin_collect_texts", ["采集此产品", "妙手采集"]),
                "successTexts": self.db.setting("automation.plugin_success_texts", ["采集成功", "已采集"]),
                "variables": {"sourceUrl": candidate["source_url"], "sourceProductId": candidate.get("source_product_id") or ""},
            })
        elif run["batch_id"]:
            batch = self.db.row("SELECT * FROM batches WHERE id=?", (run["batch_id"],))
            products = {item["id"]: item for item in self.db.list_products()}
            shops = {item["id"]: item for item in self.db.rows("SELECT * FROM shops")}
            jobs = []
            for product_id in batch["product_ids"]:
                product = products[product_id]
                versions = {item["market"]: item for item in self.db.market_versions(product_id)}
                approved = self.db.rows("SELECT * FROM assets WHERE product_id=? AND approved=1", (product_id,))
                files = [str(self.data_dir / "assets" / Path(item["url"]).name) for item in approved if item["url"].startswith("/assets/")]
                for shop_id in batch["shop_ids"]:
                    shop = shops[shop_id]
                    version = versions[shop["market"]]
                    price = round(float(version["sale_price"] or 0) * float(shop["price_multiplier"] or 1), 2)
                    jobs.append({
                        "productId": product_id, "sourceProductId": product.get("sourceProductId") or "",
                        "title": version["title"], "description": version["description"], "price": price,
                        "warehouse": version["warehouse"] or shop["warehouse"],
                        "inventory": version["inventory"] or shop["default_inventory"], "market": shop["market"],
                        "shopName": shop["shop_name"], "accountName": shop["account_name"], "entityName": shop["entity_name"],
                        "sku": product.get("sku") or product_id[:12], "category": product.get("category") or "",
                        "weightG": product.get("weightG") or 0, "lengthCm": product.get("lengthCm") or 0,
                        "widthCm": product.get("widthCm") or 0, "heightCm": product.get("heightCm") or 0,
                        "image1": files[0] if files else "", "images": files,
                    })
            payload["jobs"] = jobs
            payload["variables"] = {"batchName": batch["name"], "miaoshouUrl": payload["miaoshouUrl"]}
        elif run["kind"] == "keyword_search":
            payload.update({"url": run["context"].get("url"), "keyword": run["context"].get("keyword")})
        result = self._invoke_runner(run, payload)
        if run["kind"] == "collection" and result["status"] == "blocked":
            fallback = self.db.setting("automation.link_collection_recipe", [])
            if fallback:
                self.db.update_run(run["id"], status="running", error="", current_step="插件失败，切换妙手链接采集")
                fallback_payload = {
                    "kind": "link_collection", "port": payload["port"], "miaoshouUrl": payload["miaoshouUrl"],
                    "recipe": fallback + self.db.setting("automation.collection_recipe", []), "phase": "prepare",
                    "jobs": [payload.get("variables", {})], "variables": payload.get("variables", {}),
                }
                result = self._invoke_runner(run, fallback_payload)
        return result

    def build_diagnostics(self, run, error, failed_step="", response=None, checks=None):
        response = response or {}
        checks = checks or {}
        current_url = response.get("currentUrl") or response.get("url") or ""
        screenshot = response.get("screenshot") or ""
        clickable_text = response.get("clickableText") or response.get("clickableTexts") or []
        if isinstance(clickable_text, str):
            clickable_text = [line.strip() for line in clickable_text.splitlines() if line.strip()]
        suggestions = []
        text = str(error or "")
        if "Chrome" in text or "调试" in text:
            suggestions.append("启动专用Chrome并保持调试端口连接")
        if "登录" in text:
            suggestions.append("在专用Chrome中重新确认妙手和1688登录状态")
        if "插件" in text:
            suggestions.append("检查妙手插件是否已加载，并校准采集按钮文本")
        if "配方" in text:
            suggestions.append("在系统设置中补充采集箱认领或发布动作配方")
        if not suggestions:
            suggestions.append("展开任务详情，按当前步骤重新校准页面后重试")
        return {
            "failedStep": failed_step or run.get("current_step") or "自动化执行",
            "error": text,
            "currentUrl": current_url,
            "screenshot": screenshot,
            "clickableText": clickable_text[:20],
            "suggestedActions": suggestions,
            "checks": checks,
        }

    def mark_failed(self, run, status, error, failed_step="", response=None, checks=None):
        diagnostics = self.build_diagnostics(run, error, failed_step, response=response, checks=checks)
        return self.db.update_run(
            run["id"],
            status=status,
            error=str(error or ""),
            current_step=diagnostics["failedStep"],
            screenshot=diagnostics["screenshot"],
            diagnostics=diagnostics,
        )

    def _invoke_runner(self, run, payload):
        if payload.get("kind") == "publish" and payload.get("phase") == "confirm":
            try:
                self.ensure_publish_allowed(payload.get("recipe") or [], "最终发布确认")
            except RuntimeError as exc:
                return self.mark_failed(run, "blocked", str(exc), "no_publish 安全拦截")
        node_path = self.db.setting("automation.node_path", "node")
        script = Path(__file__).resolve().parent.parent / "scripts" / "cdp_runner.mjs"
        try:
            result = subprocess.run(
                [node_path, str(script), json.dumps(payload, ensure_ascii=False)],
                capture_output=True, text=True, timeout=240,
            )
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            response = json.loads(lines[-1]) if lines else {"ok": False, "error": result.stderr.strip() or "自动化执行器无输出"}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return self.mark_failed(run, "blocked", "自动化执行器启动失败：%s" % exc, run.get("current_step") or "启动自动化执行器")
        if not response.get("ok"):
            failed_step = response.get("failedStep") or response.get("currentStep") or response.get("step") or run.get("current_step") or "自动化执行"
            return self.mark_failed(run, "blocked", response.get("error") or "自动化执行失败", failed_step, response=response)
        steps = response.get("events") or []
        if run["kind"] == "keyword_search":
            candidates = response.get("candidates") or []
            imported = self.db.import_candidates([item["url"] for item in candidates], run["context"].get("keyword", ""))
            by_url = {item["source_url"]: item for item in imported}
            for item in candidates:
                stored = by_url.get(item["url"])
                if stored:
                    images = [item["image"]] if item.get("image") else []
                    updates = {
                        "title": item.get("title", ""),
                        "category": item.get("category") or "",
                        "source_product_id": item.get("sourceProductId") or stored.get("source_product_id") or "",
                        "source_price": item.get("sourcePrice") or stored.get("source_price") or 0,
                        "monthly_sales": item.get("monthlySales") or stored.get("monthly_sales") or 0,
                        "dispatch_hours": item.get("dispatchHours") or stored.get("dispatch_hours") or 0,
                        "images": images,
                        "image_count": len(images),
                    }
                    self.db.update_candidate(stored["id"], updates)
            status = "completed"
        elif run["kind"] == "collection":
            has_claim = bool(self.db.setting("automation.collection_recipe", []))
            status = "completed" if has_claim else "awaiting_claim"
            self.db.update_candidate(run["candidate_id"], {"status": "TikTok采集箱待优化" if status == "completed" else "公用采集箱待认领", "collected_at": int(time.time())})
        else:
            status = "completed" if payload.get("phase") == "confirm" else "waiting_confirmation"
        return self.db.update_run(run["id"], status=status, current_step=steps[-1]["label"] if steps else "完成", steps=steps)

    def run(self, run_id):
        run = self.db.get_run(run_id)
        if run["kind"] == "keyword_search" and self.is_dry_run(run):
            return self.db.update_run(run_id, status="waiting_browser", current_step="等待真实模式Chrome连接")
        if self.is_dry_run(run):
            return self.execute_dry_run(run_id)
        return self.execute_live(run_id, phase="prepare")

    def confirm_publish(self, run_id):
        run = self.db.get_run(run_id)
        if not run or run["kind"] != "publish":
            raise RuntimeError("发布任务不存在")
        if self.local_config().get("no_publish", True) and not self.is_dry_run(run):
            return self.mark_failed(run, "blocked", "no_publish=true：真实发布确认已被安全开关拦截", "no_publish 安全拦截")
        if self.is_dry_run(run):
            steps = []
            for item in run["steps"]:
                if isinstance(item, dict):
                    steps.append({**item, "status": "completed"})
                else:
                    steps.append({"label": item, "status": "completed"})
            steps.append({"label": "演练完成，未点击妙手最终发布", "status": "completed"})
            return self.db.update_run(run_id, status="completed", current_step=steps[-1]["label"], steps=steps)
        return self.execute_live(run_id, phase="confirm")
