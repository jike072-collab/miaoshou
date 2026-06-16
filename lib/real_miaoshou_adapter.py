"""Safe Miaoshou collection-box adapter backed by the dedicated Chrome session."""

import json
import subprocess
import time
from pathlib import Path

from lib.browser_manager import detect_miaoshou_login, detect_verification
from lib.local_config import assert_publish_allowed, assert_safe_collection_action, contains_publish_text, config_status, load_config


SAFE_COLLECTION_TEXTS = (
    "加入采集箱",
    "保存草稿",
    "加入待处理",
    "待处理",
    "采集箱",
    "采集",
    "保存",
)

MIAOSHOU_COLLECT_STEPS = [
    "检查安全开关",
    "校验候选准入",
    "打开妙手页面",
    "检查妙手登录态",
    "扫描危险发布按钮",
    "保存到妙手采集箱",
]


def visible_text_summary(pages, limit=30):
    texts = []
    for page in pages or []:
        for line in str(page.get("text") or "").splitlines():
            line = " ".join(line.split())
            if not line or len(line) > 80:
                continue
            if line not in texts:
                texts.append(line)
            if len(texts) >= limit:
                return texts
    return texts


def detect_dangerous_texts(texts):
    return [text for text in texts or [] if contains_publish_text(text)]


class RealMiaoshouAdapter:
    def __init__(self, database, data_dir, browser_manager):
        self.db = database
        self.data_dir = Path(data_dir)
        self.browser = browser_manager
        self.candidate_summary = None

    def config(self):
        return load_config(self.data_dir)

    def miaoshou_url(self):
        return self.db.setting("automation.miaoshou_url", "https://erp.91miaoshou.com/")

    def local_status(self):
        return config_status(self.config())

    def status(self):
        platform = self.browser.platform_status()
        records = self.db.list_collection_box_records() if hasattr(self.db, "list_collection_box_records") else []
        return {
            "status": "waiting_for_manual" if platform.get("waiting_for_manual") else "ready",
            "miaoshou_logged_in": bool(platform.get("miaoshou_logged_in")),
            "waiting_for_manual": bool(platform.get("waiting_for_manual")),
            "manual_message": platform.get("manual_message") or "",
            "current_url": platform.get("current_url") or "",
            "collection_box_records": len(records),
            "safety": self.local_status(),
            "platform": platform,
        }

    def candidate_display(self, candidate):
        if self.candidate_summary:
            try:
                summary = self.candidate_summary(candidate)
                return summary.get("displayTitle") or summary.get("cleanTitle") or summary.get("title") or ""
            except Exception:
                pass
        return (candidate or {}).get("clean_title") or (candidate or {}).get("title") or ""

    def images_used(self, candidate):
        local_images = [str(item) for item in (candidate or {}).get("local_images") or [] if str(item or "").strip()]
        if local_images:
            return local_images
        return [str(item) for item in (candidate or {}).get("images") or [] if str(item or "").strip()]

    def safe_recipe(self):
        recipe = self.db.setting("automation.miaoshou_box_recipe", [])
        if not recipe:
            recipe = self.db.setting("automation.link_collection_recipe", [])
        if not recipe:
            recipe = self.db.setting("automation.collection_recipe", [])
        return recipe or []

    def validate_candidate(self, candidate):
        config = self.config()
        reasons = []
        if not candidate:
            reasons.append("候选商品不存在")
            return False, reasons
        if not config.get("no_publish", True):
            reasons.append("no_publish 必须为 true")
        if not (config.get("dry_run_collect", True) or config.get("collect_to_box_only", False)):
            reasons.append("必须开启 dry_run_collect 或 collect_to_box_only")
        if not config.get("enable_miaoshou_collect", True):
            reasons.append("enable_miaoshou_collect 未开启")
        if (candidate.get("dedupe_status") or "new_candidate") != "new_candidate":
            reasons.append("重复候选已跳过：%s" % (candidate.get("dedupe_reason") or candidate.get("dedupe_status") or "重复"))
        if (candidate.get("precheck_status") or "") != "precheck_passed":
            reasons.append("商品预检未通过：%s" % (candidate.get("precheck_reason") or candidate.get("precheck_status") or "未预检"))
        if not (candidate.get("clean_title") or "").strip():
            reasons.append("缺少清洗后的标题")
        if (candidate.get("image_status") or "image_pending") != "image_ready":
            reasons.append("图片未就绪：%s" % (candidate.get("image_reason") or candidate.get("image_status") or "待检查"))
        existing_product = self.db.row(
            "SELECT id FROM products WHERE candidate_id=? OR (source_product_id!='' AND source_product_id=?) LIMIT 1",
            (candidate.get("id") or "", candidate.get("source_product_id") or ""),
        )
        if existing_product:
            reasons.append("已存在正式商品，避免重复采集")
        existing_box = self.db.row(
            "SELECT id FROM collection_box_records WHERE (candidate_id!='' AND candidate_id=?) OR (offer_id!='' AND offer_id=?) OR (source_url!='' AND source_url=?) LIMIT 1",
            (candidate.get("id") or "", candidate.get("source_product_id") or "", candidate.get("source_url") or ""),
        )
        if existing_box:
            reasons.append("已进入妙手采集箱，避免重复采集")
        return not reasons, reasons

    def create_run(self, candidate, status="queued", context=None):
        context = {
            "sourceUrl": candidate.get("source_url") or "",
            "sourceProductId": candidate.get("source_product_id") or "",
            "cleanTitle": candidate.get("clean_title") or "",
            "collectToBoxOnly": True,
            **(context or {}),
        }
        return self.db.create_run(
            "collection",
            list(MIAOSHOU_COLLECT_STEPS),
            candidate_id=candidate.get("id"),
            status=status,
            context=context,
        )

    def update_candidate(self, candidate_id, status):
        if candidate_id:
            self.db.update_candidate(candidate_id, {"status": status})

    def screenshot_safely(self):
        try:
            return self.browser.screenshot()
        except Exception:
            return ""

    def diagnostics(self, error, failed_step, pages=None, screenshot="", platform=None, dangerous=None):
        pages = pages or []
        clickable_text = visible_text_summary(pages)
        current_url = ""
        for page in pages:
            if "91miaoshou.com" in (page.get("url") or ""):
                current_url = page.get("url") or ""
                break
        current_url = current_url or (platform or {}).get("current_url") or ""
        suggestions = []
        text = str(error or "")
        if "登录" in text:
            suggestions.append("在专用 Chrome 中手动登录妙手后重新检测")
        if "验证码" in text or "短信" in text or "人机" in text:
            suggestions.append("在专用 Chrome 中手动完成验证，系统不会绕过验证")
        if dangerous:
            suggestions.append("页面存在发布/上架/提交类按钮，保持不点击并校准采集箱入口")
        if "结构" in text or "入口" in text:
            suggestions.append("确认妙手采集箱入口是否变化，必要时更新安全采集配置")
        if not suggestions:
            suggestions.append("检查妙手登录态、采集箱入口和候选准入后重试")
        return {
            "failedStep": failed_step or "妙手采集箱",
            "error": str(error or ""),
            "currentUrl": current_url,
            "screenshot": screenshot or "",
            "clickableText": clickable_text[:20],
            "dangerousText": list(dangerous or []),
            "suggestedActions": suggestions,
            "pageStructureChanged": "结构" in text or "入口" in text,
            "platformStatus": platform or {},
        }

    def mark_run(self, run, status, current_step, error="", diagnostics=None, screenshot=""):
        return self.db.update_run(
            run["id"],
            status=status,
            current_step=current_step,
            error=error,
            screenshot=screenshot,
            diagnostics=diagnostics or {},
        )

    def invoke_safe_recipe(self, candidate, recipe, run, pages=None, platform=None):
        try:
            assert_publish_allowed(self.config(), recipe, "妙手采集箱安全配方")
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc), "failedStep": "检查安全开关"}
        node_path = self.db.setting("automation.node_path", "node")
        script = Path(__file__).resolve().parent.parent / "scripts" / "cdp_runner.mjs"
        images = self.images_used(candidate)
        variables = {
            "sourceUrl": candidate.get("source_url") or "",
            "sourceProductId": candidate.get("source_product_id") or "",
            "title": candidate.get("clean_title") or candidate.get("title") or "",
            "cleanTitle": candidate.get("clean_title") or "",
            "originalTitle": candidate.get("title") or "",
            "image1": images[0] if images else "",
            "image2": images[1] if len(images) > 1 else "",
            "image3": images[2] if len(images) > 2 else "",
        }
        payload = {
            "kind": "link_collection",
            "port": self.browser.debug_port(),
            "miaoshouUrl": self.miaoshou_url(),
            "recipe": recipe,
            "phase": "prepare",
            "jobs": [variables],
            "variables": {
                "miaoshouUrl": self.miaoshou_url(),
                **variables,
            },
        }
        try:
            result = subprocess.run(
                [node_path, str(script), json.dumps(payload, ensure_ascii=False)],
                capture_output=True,
                text=True,
                timeout=180,
            )
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            response = json.loads(lines[-1]) if lines else {"ok": False, "error": result.stderr.strip() or "妙手采集执行器无输出"}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": "妙手采集执行器启动失败：%s" % exc, "failedStep": run.get("current_step") or "启动妙手采集执行器"}
        if not response.get("ok"):
            return {
                "ok": False,
                "error": response.get("error") or "妙手采集箱执行失败",
                "failedStep": response.get("failedStep") or response.get("currentStep") or "保存到妙手采集箱",
                "response": response,
            }
        return response

    def ensure_miaoshou_ready(self, run):
        status = self.browser.start(pages=[self.miaoshou_url()], ensure_pages=True)
        if not status.get("cdp_ready"):
            screenshot = self.screenshot_safely()
            diagnostics = self.diagnostics("专用 Chrome 未连接", "打开妙手页面", screenshot=screenshot, platform=status)
            return False, self.mark_run(run, "waiting_for_manual", "打开妙手页面", diagnostics["error"], diagnostics, screenshot), []
        platform = self.browser.platform_status()
        pages = platform.get("pages") or []
        probe = self.browser.engine.cdp_probe(self.browser.debug_port()) if platform.get("cdp_ready") else {}
        full_pages = probe.get("pages") or pages
        verification = detect_verification(full_pages)
        miaoshou = detect_miaoshou_login(full_pages)
        if verification.get("detected"):
            screenshot = self.screenshot_safely()
            message = "检测到验证码/人机/短信验证，请人工处理"
            diagnostics = self.diagnostics(message, "检查妙手登录态", full_pages, screenshot, platform)
            return False, self.mark_run(run, "waiting_for_manual", "检查妙手登录态", message, diagnostics, screenshot), full_pages
        if miaoshou.get("needs_login") or not miaoshou.get("logged_in"):
            screenshot = self.screenshot_safely()
            message = "妙手未登录，请在专用 Chrome 中手动登录"
            diagnostics = self.diagnostics(message, "检查妙手登录态", full_pages, screenshot, platform)
            return False, self.mark_run(run, "waiting_for_manual", "检查妙手登录态", message, diagnostics, screenshot), full_pages
        return True, platform, full_pages

    def collect_candidate(self, candidate, run=None):
        run = run or self.create_run(candidate, status="running")
        config = self.config()
        try:
            assert_safe_collection_action(config, "加入采集箱 保存草稿 加入待处理", "妙手采集箱流程")
        except RuntimeError as exc:
            diagnostics = self.diagnostics(str(exc), "检查安全开关")
            self.update_candidate(candidate.get("id"), "人工处理")
            return self.mark_run(run, "blocked", "检查安全开关", str(exc), diagnostics)

        valid, reasons = self.validate_candidate(candidate)
        if not valid:
            message = "；".join(reasons)
            diagnostics = self.diagnostics(message, "校验候选准入")
            self.update_candidate(candidate.get("id"), "人工处理")
            return self.mark_run(run, "blocked", "校验候选准入", message, diagnostics)

        self.update_candidate(candidate.get("id"), "opening_miaoshou")
        self.db.update_run(run["id"], status="running", current_step="打开妙手页面", error="")
        ready, result, pages = self.ensure_miaoshou_ready(run)
        if not ready:
            self.update_candidate(candidate.get("id"), "waiting_for_manual")
            return result

        clickable_text = visible_text_summary(pages)
        dangerous = detect_dangerous_texts(clickable_text)
        safe_text = " ".join(list(SAFE_COLLECTION_TEXTS))
        try:
            assert_safe_collection_action(config, safe_text, "妙手页面可点击文本")
        except RuntimeError as exc:
            screenshot = self.screenshot_safely()
            diagnostics = self.diagnostics(str(exc), "扫描危险发布按钮", pages, screenshot, result, dangerous)
            self.update_candidate(candidate.get("id"), "waiting_for_manual")
            return self.mark_run(run, "waiting_for_manual", "扫描危险发布按钮", str(exc), diagnostics, screenshot)

        recipe = self.safe_recipe()
        if not recipe:
            screenshot = self.screenshot_safely()
            message = "妙手采集箱安全配方未配置，请先校准“加入采集箱/保存草稿/待处理”动作"
            diagnostics = self.diagnostics(message, "保存到妙手采集箱", pages, screenshot, result, dangerous)
            self.update_candidate(candidate.get("id"), "waiting_for_manual")
            return self.mark_run(run, "waiting_for_manual", "保存到妙手采集箱", message, diagnostics, screenshot)

        self.update_candidate(candidate.get("id"), "collecting_to_box")
        self.db.update_run(run["id"], status="running", current_step="保存到妙手采集箱", error="")
        execution = self.invoke_safe_recipe(candidate, recipe, run, pages=pages, platform=result)
        if not execution.get("ok"):
            screenshot = self.screenshot_safely()
            message = execution.get("error") or "妙手采集箱执行失败"
            diagnostics = self.diagnostics(message, execution.get("failedStep") or "保存到妙手采集箱", pages, screenshot, result, dangerous)
            diagnostics["runnerResponse"] = execution.get("response") or {}
            self.update_candidate(candidate.get("id"), "collect_failed")
            return self.mark_run(run, "blocked", diagnostics["failedStep"], message, diagnostics, screenshot)

        images = self.images_used(candidate)
        record = self.db.save_collection_box_record({
            "candidate_id": candidate.get("id") or "",
            "offer_id": candidate.get("source_product_id") or "",
            "source_url": candidate.get("source_url") or "",
            "clean_title": candidate.get("clean_title") or self.candidate_display(candidate),
            "image_status": candidate.get("image_status") or "",
            "images_used": images,
            "collected_at": int(time.time()),
            "miaoshou_status": "collected_to_box",
            "run_id": run["id"],
        })
        self.db.update_candidate(candidate.get("id"), {
            "status": "collected_to_box",
            "collection_channel": "miaoshou_box_only",
            "collected_at": record.get("collected_at") or int(time.time()),
        })
        context = {**(run.get("context") or {}), "recordId": record["id"], "imagesUsed": images, "collectToBoxOnly": True}
        steps = [
            {"label": step, "status": "completed"}
            for step in MIAOSHOU_COLLECT_STEPS
        ]
        return self.db.update_run(
            run["id"],
            status="completed",
            current_step="保存到妙手采集箱",
            steps=steps,
            error="",
            context=context,
            diagnostics={
                "failedStep": "",
                "error": "",
                "currentUrl": result.get("current_url") or "",
                "screenshot": "",
                "clickableText": clickable_text[:20],
                "dangerousText": dangerous,
                "suggestedActions": ["已保存到妙手采集箱/待处理区，未进入发布流程"],
                "recordId": record["id"],
                "runnerEvents": execution.get("events") or [],
            },
        )

    def collect_ready(self, candidate_ids=None):
        ids = [str(item) for item in (candidate_ids or []) if str(item or "").strip()]
        candidates = self.db.list_candidates()
        if ids:
            candidates = [item for item in candidates if item.get("id") in ids]
        created, blocked = [], []
        for candidate in candidates:
            valid, reasons = self.validate_candidate(candidate)
            if not valid:
                blocked.append({
                    "id": candidate.get("id") or "",
                    "title": self.candidate_display(candidate) or candidate.get("source_product_id") or "",
                    "error": "；".join(reasons),
                })
                continue
            run = self.create_run(candidate, status="running")
            result = self.collect_candidate(candidate, run=run)
            if result.get("status") == "completed":
                created.append(result)
            else:
                blocked.append({
                    "id": candidate.get("id") or "",
                    "runId": run["id"],
                    "title": self.candidate_display(candidate) or candidate.get("source_product_id") or "",
                    "status": result.get("status"),
                    "error": result.get("error") or (result.get("diagnostics") or {}).get("error") or "",
                    "diagnostics": result.get("diagnostics") or {},
                })
        return {
            "items": created,
            "blocked": blocked,
            "records": self.db.list_collection_box_records() if hasattr(self.db, "list_collection_box_records") else [],
            "status": self.status(),
        }
