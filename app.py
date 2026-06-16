#!/usr/bin/env python3
"""Miaoshou intelligent sourcing and automation workbench."""

import base64
import csv
import io
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from difflib import SequenceMatcher
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from lib.automation import AutomationEngine, source_product_id
from lib.browser_manager import BrowserManager
from lib.collector import CollectError, fetch_image, scrape_product
from lib.database import Database, MARKETS
from lib.evaluation import evaluate_candidate, evaluation_status
from lib.image_inspector import analyze_candidate_images, make_image_record_payload
from lib.image_gateway import ImageGatewayError, generate
from lib.keychain import get_secret, set_secret
from lib.local_config import config_status, ensure_local_runtime, load_config, load_or_create_token, save_config
from lib.prompts import PRESETS, build_prompts
from lib.real1688_adapter import Real1688Adapter, SOURCING_ACTIVE_STATUSES
from lib.text_gateway import TextGatewayError, localize
from lib.title_cleaner import TitleCleaner


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.environ.get("WORKBENCH_DATA_DIR", str(ROOT / "data"))).resolve()
ensure_local_runtime(DATA_DIR)
ASSET_DIR = DATA_DIR / "assets"
DB = Database(DATA_DIR / "workbench.db")
AUTOMATION = AutomationEngine(DB, DATA_DIR)
BROWSER = BrowserManager(DB, DATA_DIR)
SOURCING = Real1688Adapter(DB, DATA_DIR, BROWSER)
TITLE_CLEANER = TitleCleaner()
WORKBENCH_TOKEN = load_or_create_token(DATA_DIR)
RUN_LOCK = threading.Lock()
ACTIVE_RUNS = set()
SOURCING_LOCK = threading.Lock()
ACTIVE_SOURCING_RUNS = set()
GENERATION_LOCK = threading.Lock()
ACTIVE_GENERATIONS = set()
GENERATION_SLOTS = threading.BoundedSemaphore(max(1, int(DB.setting("image.concurrency", 2))))

MARKET_INFO = {
    "MY": {"name": "马来西亚", "language": "en", "currency": "MYR"},
    "PH": {"name": "菲律宾", "language": "en", "currency": "PHP"},
    "SG": {"name": "新加坡", "language": "en", "currency": "SGD"},
    "TH": {"name": "泰国", "language": "th", "currency": "THB"},
    "VN": {"name": "越南", "language": "vi", "currency": "VND"},
}

IMAGE_QUEUE_DEFINITIONS = [
    ("needs_generation", "待生图"),
    ("generating", "生图中"),
    ("generation_success", "生图成功"),
    ("generation_failed", "生图失败"),
    ("awaiting_approval", "待审核"),
    ("approved", "审核通过"),
    ("rejected", "审核不通过"),
]

COLLECTION_QUEUE_DEFINITIONS = [
    ("pending", "待采集"),
    ("running", "采集中"),
    ("completed", "采集成功"),
    ("failed", "采集失败"),
    ("manual", "需人工处理"),
]

DEDUPE_STATUS_LABELS = {
    "new_candidate": "新候选",
    "duplicate_offer_id": "Offer ID重复",
    "duplicate_url": "链接重复",
    "duplicate_title": "标题重复",
    "duplicate_image": "主图重复",
    "already_collected_to_box": "已进入采集箱",
    "needs_manual_duplicate_check": "疑似重复",
}

DEDUPE_SKIP_STATUSES = {
    "duplicate_offer_id",
    "duplicate_url",
    "duplicate_title",
    "duplicate_image",
    "already_collected_to_box",
    "needs_manual_duplicate_check",
}

PRECHECK_STATUS_LABELS = {
    "not_checked": "未预检",
    "precheck_passed": "预检通过",
    "needs_title_clean": "需清洗标题",
    "needs_image_check": "需图片检查",
    "low_priority_skipped": "低优先级跳过",
    "risk_blocked": "风险阻断",
    "precheck_failed": "预检失败",
}

IMAGE_STATUS_LABELS = {
    "image_pending": "待检查",
    "original_usable": "原图可用",
    "needs_cleanup": "需处理",
    "needs_generation": "需生图",
    "image_processing": "处理中",
    "image_ready": "图片已就绪",
    "image_failed": "图片失败",
}

PRECHECK_BLOCK_STATUSES = {
    "not_checked",
    "needs_title_clean",
    "needs_image_check",
    "low_priority_skipped",
    "risk_blocked",
    "precheck_failed",
}

RISK_KEYWORD_GROUPS = [
    ("品牌侵权/大牌仿品", ("原单", "高仿", "复刻", "大牌", "莆田", "尾货", "仿品", "假货", "nike", "adidas", "lv", "gucci", "chanel", "dior", "prada", "balenciaga")),
    ("医疗或药品功效", ("医疗", "治疗", "治愈", "医用", "药品", "械字号", "降压", "降糖", "根治", "止痛", "抗菌消炎")),
    ("减肥或夸大功效", ("减肥", "瘦身", "丰胸", "永久", "100%", "百分百", "奇效", "神器", "立刻见效", "虚假宣传", "夸大功效")),
    ("成人敏感品", ("成人", "情趣", "避孕", "私处", "催情")),
    ("武器刀具", ("刀具", "匕首", "砍刀", "武器", "电击", "弓弩", "弹弓", "防身器")),
    ("违禁或需资质", ("违禁", "违禁药", "保健品", "食品", "化妆品", "三无", "处方", "电子烟")),
]

TITLE_CLEAN_NOISE = (
    "厂家直销", "源头工厂", "一件代发", "跨境", "外贸", "批发", "包邮", "爆款",
    "新款", "网红", "抖音", "淘宝", "天猫", "1688", "现货", "支持代发",
)

SUMMER_TOKENS = ("透气", "凉鞋", "防滑", "轻便", "户外", "速干", "网面", "清凉", "沙滩")
RAINY_TOKENS = ("防滑", "防水", "防潮", "雨", "速干", "涉水")
FESTIVAL_TOKENS = ("礼品", "装饰", "配饰", "节日", "圣诞", "新年", "派对")
OFF_SEASON_WARM_TOKENS = ("加绒", "羽绒", "保暖", "雪地", "棉靴", "暖手", "厚棉", "毛绒")
SEA_GOOD_TOKENS = ("透气", "凉鞋", "防滑", "防水", "轻便", "户外", "收纳", "配饰", "运动", "包", "鞋", "家居")
CONTENT_FRIENDLY_TOKENS = ("新奇", "懒人", "收纳", "装饰", "配饰", "鞋", "包", "运动", "户外", "防滑", "变形", "多功能")
BULKY_OR_FRAGILE_TOKENS = ("家具", "大件", "桌", "椅", "床", "玻璃", "陶瓷", "瓷器", "大型", "重型")

REJECTION_REASONS = ["鞋子变形", "颜色不一致", "文字错误", "Logo 错误", "背景杂乱", "主体不清晰", "风格不符合平台", "其他"]

WORKFLOW_STAGE_LABELS = {
    "candidate_imported": "候选导入",
    "candidate_need_data": "待补数据",
    "candidate_ready_to_score": "可评分",
    "candidate_scored": "已评分",
    "candidate_collectable": "可采集",
    "product_collected": "已采集",
    "image_needs_generation": "待生图",
    "image_generating": "生图中",
    "image_awaiting_review": "待审核",
    "image_approved": "图片通过",
    "ready_to_batch": "可铺货",
    "batch_precheck": "批次预检",
    "dry_run_passed": "演练通过",
    "live_publishing": "真实发布",
    "publish_completed": "发布完成",
    "failure_handling": "失败处理",
}


def initialize():
    ensure_local_runtime(DATA_DIR)
    SOURCING.dedupe_callback = lambda candidate_ids: dedupe_candidates(candidate_ids)
    SOURCING.precheck_callback = lambda candidate_ids: precheck_candidates(candidate_ids)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    apply_config_to_settings()
    DB.migrate_products_json(DATA_DIR / "products.json")
    DB.execute("UPDATE automation_runs SET status='queued',error='服务重启后等待恢复' WHERE status IN ('running','preparing')")
    DB.execute("UPDATE generation_jobs SET status='queued',error='服务重启后等待恢复' WHERE status='running'")


def workbench_config():
    return load_config(DATA_DIR)


def apply_config_to_settings(config=None):
    config = config or workbench_config()
    DB.set_settings({
        "automation.cdp_port": int(config.get("chrome_debug_port") or 9222),
        "automation.chrome_profile_dir": config.get("chrome_profile_dir") or "data/chrome-profile",
    })
    return config


def local_status():
    config = workbench_config()
    return {
        "ok": True,
        "host": "127.0.0.1",
        "dataDir": str(DATA_DIR),
        "configPath": str(DATA_DIR / "config.json"),
        "token": WORKBENCH_TOKEN,
        "config": config,
        **config_status(config),
    }


def workbench_token_valid(handler):
    return handler.headers.get("X-Workbench-Token", "") == WORKBENCH_TOKEN


def is_loopback_client(handler):
    host = handler.client_address[0] if handler.client_address else ""
    return host in ("127.0.0.1", "::1", "localhost")


def reject_unsafe_publish_payload(payload):
    config = workbench_config()
    if config.get("no_publish", True) and not bool(payload.get("dryRun", True)):
        raise ValueError("no_publish=true：禁止创建真实发布批次，请保持演练模式")


def block_run_for_manual(run, platform):
    message = platform.get("manual_message") or "请在专用 Chrome 中完成登录或验证后继续"
    diagnostics = {
        "failedStep": "等待人工验证",
        "error": message,
        "currentUrl": platform.get("current_url") or "",
        "screenshot": "",
        "clickableText": [],
        "suggestedActions": ["在专用 Chrome 中手动完成登录/验证码/短信验证", "完成后点击环境状态里的重新检测，再重试任务"],
        "platformStatus": platform,
    }
    return DB.update_run(
        run["id"],
        status="waiting_for_manual",
        current_step="等待人工处理",
        error=message,
        diagnostics=diagnostics,
    )


def json_body(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ValueError("请求长度无效")
    if length <= 0 or length > 20 * 1024 * 1024:
        raise ValueError("请求内容为空或超过 20MB")
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("请求 JSON 格式无效")


def normalize_url(value):
    value = str(value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("链接必须是完整的 http:// 或 https:// 地址")
    return value


def normalize_source_url_for_dedupe(value):
    value = str(value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parsed.path or "")
    offer_id = source_product_id(value)
    if offer_id:
        return "1688:%s" % offer_id
    return "%s%s" % (host, path)


def clean_title_for_dedupe(title):
    text = str(title or "").lower()
    text = re.sub(r"[\s\-_/|,，.。:：;；!！?？()（）【】\\[\\]{}<>《》\"'“”‘’]+", "", text)
    noise = (
        "厂家直销", "跨境", "一件代发", "现货", "批发", "包邮", "新款", "爆款",
        "源头工厂", "支持代发", "1688", "淘宝", "天猫", "抖音",
    )
    for marker in noise:
        text = text.replace(marker, "")
    return text[:120]


def image_fingerprint(value):
    value = str(value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    path = re.sub(r"_(?:\d+x\d+|sum|!!.*)$", "", parsed.path or "")
    return "%s%s" % (host, path)


def primary_candidate_image(candidate):
    images = candidate.get("images") or []
    if images:
        return images[0]
    return candidate.get("main_image_url") or ""


def candidate_image_status(candidate):
    return str((candidate or {}).get("image_status") or "image_pending")


def candidate_image_ready(candidate):
    return candidate_image_status(candidate) == "image_ready"


def candidate_dedupe_status(candidate):
    return str((candidate or {}).get("dedupe_status") or "new_candidate")


def candidate_is_duplicate_skipped(candidate):
    return candidate_dedupe_status(candidate) in DEDUPE_SKIP_STATUSES


def candidate_precheck_status(candidate):
    return str((candidate or {}).get("precheck_status") or "")


def candidate_precheck_text(candidate):
    return " ".join(
        str((candidate or {}).get(field) or "")
        for field in ("title", "category", "supplier_name", "sales_text", "origin_place")
    ).strip()


def candidate_precheck_signature(candidate):
    candidate = candidate or {}
    images = candidate.get("images") or []
    values = [
        candidate.get("title") or "",
        candidate.get("clean_title") or "",
        str(candidate.get("title_cleaned_at") or 0),
        candidate.get("category") or "",
        candidate.get("supplier_name") or "",
        candidate.get("sales_text") or "",
        candidate.get("origin_place") or "",
        str(candidate.get("source_price") or 0),
        str(candidate.get("weight_g") or 0),
        str(candidate.get("image_count") or 0),
        str(bool(candidate.get("sku_complete"))),
        "|".join(str(item or "") for item in images[:5]),
    ]
    return clean_title_for_dedupe("||".join(values))


def candidate_precheck_effective(candidate):
    candidate = candidate or {}
    stored_status = candidate_precheck_status(candidate)
    checked_at = int(candidate.get("precheck_checked_at") or 0)
    updated_at = int(candidate.get("updated_at") or 0)
    details = candidate.get("precheck_details") or {}
    current_signature = candidate_precheck_signature(candidate)
    if (
        stored_status
        and checked_at
        and checked_at >= updated_at
        and details.get("sourceSignature") == current_signature
    ):
        return {
            "precheck_status": stored_status or "not_checked",
            "precheck_reason": str(candidate.get("precheck_reason") or ""),
            "precheck_reasons": candidate.get("precheck_reasons") or [],
            "precheck_details": details,
            "sea_fit_status": str(candidate.get("sea_fit_status") or ""),
            "season_fit_status": str(candidate.get("season_fit_status") or ""),
            "precheck_checked_at": checked_at,
            "persisted": True,
        }
    analysis = analyze_candidate_precheck(candidate)
    analysis["persisted"] = False
    return analysis


def text_has_any(text, tokens):
    haystack = str(text or "").lower()
    return any(str(token or "").lower() in haystack for token in tokens if str(token or "").strip())


def candidate_risk_hits(candidate):
    text = candidate_precheck_text(candidate).lower()
    hits = []
    for label, tokens in RISK_KEYWORD_GROUPS:
        matched = [token for token in tokens if str(token or "").lower() in text]
        if matched:
            hits.append({"label": label, "tokens": matched})
    return hits


def candidate_title_quality(candidate):
    title = candidate_display_title(candidate)
    cleaned = clean_title_for_dedupe(title)
    if not title:
        return False, "标题缺失"
    if len(cleaned) < 4:
        return False, "标题过短或不可识别"
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", cleaned):
        return False, "标题缺少有效商品词"
    return True, ""


def candidate_title_needs_clean(candidate):
    clean_title = candidate_clean_title(candidate)
    if clean_title:
        return TITLE_CLEANER.has_supply_or_platform_terms(clean_title) or text_has_any(clean_title, TITLE_CLEAN_NOISE)
    title = str((candidate or {}).get("title") or "").strip()
    return text_has_any(title, TITLE_CLEAN_NOISE) or TITLE_CLEANER.has_supply_or_platform_terms(title)


def candidate_clean_title(candidate):
    candidate = candidate or {}
    return str(candidate.get("clean_title") or "").strip()


def candidate_display_title(candidate):
    candidate = candidate or {}
    return candidate_clean_title(candidate) or str(candidate.get("title") or "").strip()


def title_clean_record_payload(candidate, result, product_id=""):
    return {
        "candidate_id": (candidate or {}).get("id") or "",
        "product_id": product_id or "",
        "original_title": result.get("original_title") or "",
        "clean_title": result.get("clean_title") or "",
        "removed_terms": result.get("removed_terms") or [],
        "risk_terms": result.get("risk_terms") or [],
        "status": result.get("status") or "title_cleaned",
        "cleaned_at": result.get("cleaned_at") or int(time.time()),
    }


def clean_candidate_title(candidate_id, persist=True):
    candidate = DB.get_candidate(candidate_id)
    if not candidate:
        raise ValueError("候选商品不存在")
    result = TITLE_CLEANER.clean(candidate.get("title") or "")
    cleaned_at = int(time.time())
    result["cleaned_at"] = cleaned_at
    if persist:
        DB.update_candidate(candidate_id, {
            "clean_title": result["clean_title"],
            "title_clean_removed_terms": result["removed_terms"],
            "title_clean_risk_terms": result["risk_terms"],
            "title_cleaned_at": cleaned_at,
            "precheck_status": "",
            "precheck_reason": "",
            "precheck_reasons": [],
            "precheck_details": {},
            "precheck_checked_at": None,
        })
        if hasattr(DB, "save_title_cleaning_record"):
            DB.save_title_cleaning_record(title_clean_record_payload(candidate, result))
    return result


def clean_titles_for_candidates(candidate_ids=None):
    ids = candidate_ids or [item["id"] for item in DB.list_candidates()]
    items, blocked = [], []
    for candidate_id in ids:
        try:
            result = clean_candidate_title(candidate_id)
            precheck = precheck_candidates([candidate_id])
            summary = (precheck.get("items") or [candidate_summary(DB.get_candidate(candidate_id))])[0]
            items.append({**result, "candidate": summary})
        except Exception as exc:
            candidate = DB.get_candidate(candidate_id)
            blocked.append({
                "id": candidate_id,
                "title": (candidate or {}).get("title") or candidate_id,
                "error": str(exc),
            })
    return {"items": items, "blocked": blocked, "cleaned": len(items)}


def image_dir_for_candidate(candidate_id):
    path = DATA_DIR / "images" / str(candidate_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def update_candidate_image_result(candidate, summary):
    checked_at = int(time.time())
    status = summary.get("status") or "image_pending"
    reasons = summary.get("reasons") or []
    local_paths = summary.get("local_paths") or []
    updated = DB.update_candidate(candidate["id"], {
        "image_status": status,
        "image_reason": "；".join(reasons[:3]) if reasons else ("原图可用" if status == "image_ready" else ""),
        "image_reasons": reasons,
        "image_details": summary.get("details") or {},
        "image_checked_at": checked_at,
        "local_images": local_paths,
    })
    if hasattr(DB, "save_image_analysis_record"):
        DB.save_image_analysis_record(make_image_record_payload(candidate, {
            **summary,
            "status": status,
        }, image_path=local_paths[0] if local_paths else ""))
    return updated


def download_candidate_images(candidate_ids=None):
    ids = candidate_ids or [item["id"] for item in DB.list_candidates()]
    items, blocked = [], []
    for candidate_id in ids:
        candidate = DB.get_candidate(candidate_id)
        if not candidate:
            blocked.append({"id": candidate_id, "error": "候选商品不存在"})
            continue
        try:
            summary = analyze_candidate_images(candidate, image_dir=image_dir_for_candidate(candidate_id))
            updated = update_candidate_image_result(candidate, summary)
            items.append({
                "candidate": candidate_summary(updated),
                "status": updated.get("image_status"),
                "downloaded": len(summary.get("local_paths") or []),
                "failed": summary.get("failed") or [],
                "items": summary.get("items") or [],
            })
        except Exception as exc:
            blocked.append({"id": candidate_id, "title": candidate.get("title") or candidate_id, "error": str(exc)})
    return {"items": items, "blocked": blocked, "downloaded": sum(item.get("downloaded") or 0 for item in items)}


def analyze_candidate_images_for_ids(candidate_ids=None):
    ids = candidate_ids or [item["id"] for item in DB.list_candidates()]
    items, blocked = [], []
    for candidate_id in ids:
        candidate = DB.get_candidate(candidate_id)
        if not candidate:
            blocked.append({"id": candidate_id, "error": "候选商品不存在"})
            continue
        try:
            summary = analyze_candidate_images(candidate, image_dir=image_dir_for_candidate(candidate_id))
            updated = update_candidate_image_result(candidate, summary)
            items.append({
                "candidate": candidate_summary(updated),
                "status": updated.get("image_status"),
                "reasons": updated.get("image_reasons") or [],
                "details": updated.get("image_details") or {},
                "localImages": updated.get("local_images") or [],
                "items": summary.get("items") or [],
            })
        except Exception as exc:
            blocked.append({"id": candidate_id, "title": candidate.get("title") or candidate_id, "error": str(exc)})
    return {
        "items": items,
        "blocked": blocked,
        "ready": sum(1 for item in items if item.get("status") == "image_ready"),
        "needsGeneration": sum(1 for item in items if item.get("status") == "needs_generation"),
        "failed": sum(1 for item in items if item.get("status") == "image_failed") + len(blocked),
    }


def auto_process_candidate_images(candidate_ids=None):
    result = analyze_candidate_images_for_ids(candidate_ids)
    processed = []
    blocked = list(result.get("blocked") or [])
    for item in result.get("items") or []:
        candidate = item.get("candidate") or {}
        if item.get("status") == "image_ready":
            processed.append(item)
            continue
        blocked.append({
            "id": candidate.get("id") or "",
            "title": candidate.get("title") or candidate.get("source_product_id") or "",
            "imageStatus": item.get("status"),
            "imageStatusLabel": IMAGE_STATUS_LABELS.get(item.get("status"), item.get("status")),
            "imageReasons": item.get("reasons") or [],
            "error": "图片未达标，不能进入妙手采集箱",
        })
    return {
        **result,
        "processed": processed,
        "blocked": blocked,
    }


def current_season_fit_status(candidate, month=None):
    month = int(month or time.localtime().tm_mon or 0)
    text = candidate_precheck_text(candidate)
    reasons = []
    good = False
    poor = False
    warm_months = {4, 5, 6, 7, 8, 9, 10}
    rainy_months = {5, 6, 7, 8, 9, 10}
    festival_months = {1, 2, 11, 12}
    if month in warm_months and text_has_any(text, SUMMER_TOKENS):
        reasons.append("适合当前热季或夏季")
        good = True
    if month in rainy_months and text_has_any(text, RAINY_TOKENS):
        reasons.append("适合雨季")
        good = True
    if month in festival_months and text_has_any(text, FESTIVAL_TOKENS):
        reasons.append("适合节日季")
        good = True
    if text_has_any(text, OFF_SEASON_WARM_TOKENS) and month in warm_months | rainy_months | festival_months:
        reasons.append("明显偏冬季/保暖商品")
        poor = True
    if text_has_any(text, ("羽绒", "加厚", "保暖", "雪地")) and month in warm_months | rainy_months:
        poor = True
    if good and not poor:
        return "season_fit_good", reasons or ["适合当前季节"], []
    if poor and not good:
        return "season_fit_poor", reasons or ["不符合当前季节"], []
    return "season_fit_normal", reasons or ["季节适配一般"], []


def sea_fit_status(candidate):
    text = candidate_precheck_text(candidate)
    price = float((candidate or {}).get("source_price") or 0)
    weight = float((candidate or {}).get("weight_g") or 0)
    reasons = []
    score = 0
    if text_has_any(text, SEA_GOOD_TOKENS):
        score += 2
        reasons.append("适合东南亚气候和内容展示")
    if text_has_any(text, CONTENT_FRIENDLY_TOKENS):
        score += 1
        reasons.append("适合 TikTok 冲动消费展示")
    if 0 < price <= 120:
        score += 2
        reasons.append("价格带适合东南亚市场")
    elif 120 < price <= 220:
        score += 1
        reasons.append("价格带中等")
    elif price > 220:
        score -= 2
        reasons.append("价格偏高")
    if 0 < weight <= 1000:
        score += 2
        reasons.append("重量较轻，物流更友好")
    elif 1000 < weight <= 2500:
        score += 1
        reasons.append("重量可接受")
    elif weight > 2500:
        score -= 2
        reasons.append("重量偏重")
    if text_has_any(text, BULKY_OR_FRAGILE_TOKENS):
        score -= 2
        reasons.append("体积大或易碎，不利于跨境物流")
    if text_has_any(text, OFF_SEASON_WARM_TOKENS):
        score -= 1
        reasons.append("偏厚重/保暖，不利于 SEA 日常消费")
    if score >= 5:
        return "sea_fit_good", reasons or ["适合东南亚市场"], score
    if score >= 1:
        return "sea_fit_normal", reasons or ["东南亚适配一般"], score
    return "sea_fit_poor", reasons or ["东南亚适配较弱"], score


def analyze_candidate_precheck(candidate, month=None):
    candidate = candidate or {}
    reasons = []
    risk_hits = candidate_risk_hits(candidate)
    title_ok, title_reason = candidate_title_quality(candidate)
    title_needs_clean = candidate_title_needs_clean(candidate)
    images = candidate.get("images") or []
    image_count = int(candidate.get("image_count") or len([item for item in images if item]) or 0)
    sku_complete = bool(candidate.get("sku_complete"))
    source_price = float(candidate.get("source_price") or 0)
    weight_g = float(candidate.get("weight_g") or 0)
    category = str(candidate.get("category") or "").strip() or infer_candidate_category(candidate.get("title"), "")
    season_status, season_reasons, season_score = current_season_fit_status(candidate, month=month)
    sea_status, sea_reasons, sea_score = sea_fit_status(candidate)
    title_needed = not title_ok or title_needs_clean
    image_needed = image_count < 3
    basic_missing = []
    if not sku_complete:
        basic_missing.append("sku_complete")
    if source_price <= 0:
        basic_missing.append("source_price")
    if weight_g <= 0:
        basic_missing.append("weight_g")
    if not category:
        basic_missing.append("category")
    if risk_hits:
        reasons.extend(["%s：%s" % (item["label"], "、".join(item["tokens"])) for item in risk_hits])
    if title_needed:
        reasons.append(title_reason or "标题含1688营销词，需要清洗")
    if image_needed:
        reasons.append("图片数量不足，需要补图")
    if basic_missing:
        reasons.append("基础字段缺失：" + "、".join(basic_missing))
    if season_status == "season_fit_poor":
        reasons.extend(season_reasons)
    if sea_status == "sea_fit_poor":
        reasons.extend(sea_reasons)
    status = "precheck_passed"
    if risk_hits:
        status = "risk_blocked"
    elif title_needed:
        status = "needs_title_clean"
    elif image_needed:
        status = "needs_image_check"
    elif basic_missing:
        status = "precheck_failed"
    elif season_status == "season_fit_poor" or sea_status == "sea_fit_poor":
        status = "low_priority_skipped"
    if status == "precheck_passed":
        reason_text = "；".join(reasons) if reasons else "通过预检"
    elif status == "risk_blocked":
        reason_text = "；".join(reasons) or "高风险商品"
    elif status == "needs_title_clean":
        reason_text = title_reason or "标题需要清洗"
    elif status == "needs_image_check":
        reason_text = "图片数量不足"
    elif status == "low_priority_skipped":
        reason_text = "；".join(season_reasons + sea_reasons) or "低优先级跳过"
    else:
        reason_text = "；".join(reasons) or "基础字段不完整"
    details = {
        "titleCleanable": title_ok,
        "titleNeedsClean": title_needed,
        "titleReason": title_reason or ("标题含1688营销词，需要清洗" if title_needs_clean else ""),
        "imageCount": image_count,
        "imageThreshold": 3,
        "skuComplete": sku_complete,
        "sourcePrice": source_price,
        "weightG": weight_g,
        "category": category,
        "missingBasicFields": basic_missing,
        "riskHits": risk_hits,
        "riskCount": len(risk_hits),
        "seasonFitStatus": season_status,
        "seasonReasons": season_reasons,
        "seasonScore": season_score,
        "seaFitStatus": sea_status,
        "seaReasons": sea_reasons,
        "seaScore": sea_score,
        "currentMonth": int(month or time.localtime().tm_mon or 0),
        "sourceSignature": candidate_precheck_signature(candidate),
        "suggestedAction": {
            "risk_blocked": "直接跳过",
            "needs_title_clean": "先清洗标题再继续",
            "needs_image_check": "补足商品图片后再继续",
            "precheck_failed": "补齐价格、重量、类目或 SKU",
            "low_priority_skipped": "降级处理或暂缓采集",
            "precheck_passed": "可以继续进入后续流程",
        }.get(status, "继续检查"),
    }
    return {
        "precheck_status": status,
        "precheck_reason": reason_text,
        "precheck_reasons": reasons or ([reason_text] if reason_text else []),
        "precheck_details": details,
        "sea_fit_status": sea_status,
        "season_fit_status": season_status,
        "precheck_checked_at": int(time.time()),
    }


def precheck_candidates(candidate_ids=None, month=None):
    ids = candidate_ids or [item["id"] for item in DB.list_candidates()]
    items = []
    counts = {
        "precheck_passed": 0,
        "needs_title_clean": 0,
        "needs_image_check": 0,
        "low_priority_skipped": 0,
        "risk_blocked": 0,
        "precheck_failed": 0,
    }
    missing = []
    for candidate_id in ids:
        candidate = DB.get_candidate(candidate_id)
        if not candidate:
            missing.append({"id": candidate_id, "error": "候选商品不存在"})
            continue
        analysis = analyze_candidate_precheck(candidate, month=month)
        updated = DB.update_candidate(candidate_id, analysis)
        summary = candidate_summary(updated)
        items.append(summary)
        status = summary.get("precheckStatus") or "precheck_failed"
        if status in counts:
            counts[status] += 1
    return {
        "items": items,
        "missing": missing,
        "counts": counts,
        "checked": len(items),
        "summary": {
            "passed": counts["precheck_passed"],
            "riskBlocked": counts["risk_blocked"],
            "lowPrioritySkipped": counts["low_priority_skipped"],
            "failed": counts["precheck_failed"] + counts["needs_title_clean"] + counts["needs_image_check"],
        },
    }


def encode_1688_keyword(keyword):
    try:
        return quote(keyword.encode("gbk"))
    except UnicodeEncodeError:
        return quote(keyword)


def save_data_image(data_url):
    match = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", str(data_url), re.DOTALL)
    if not match:
        raise ValueError("仅支持 PNG、JPEG 或 WebP 图片")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError("图片数据无效")
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError("图片不能超过 12MB")
    extension = "jpg" if match.group(1) == "jpeg" else match.group(1)
    filename = "%s.%s" % (uuid.uuid4().hex, extension)
    (ASSET_DIR / filename).write_bytes(raw)
    return "/assets/" + filename


def products_to_csv(products):
    output = io.StringIO()
    fields = ["商品ID", "商品标题", "SKU", "状态", "类目", "来源链接", "主图", "来源价", "采购成本", "建议售价", "币种", "重量(g)", "长(cm)", "宽(cm)", "高(cm)", "备注"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in products:
        writer.writerow({
            "商品ID": item.get("id", ""), "商品标题": item.get("title", ""), "SKU": item.get("sku", ""),
            "状态": item.get("status", ""), "类目": item.get("category", ""), "来源链接": item.get("sourceUrl", ""),
            "主图": item.get("mainImage", ""), "来源价": item.get("sourcePrice", 0), "采购成本": item.get("costPrice", 0),
            "建议售价": item.get("salePrice", 0), "币种": item.get("currency", "CNY"), "重量(g)": item.get("weightG", 0),
            "长(cm)": item.get("lengthCm", 0), "宽(cm)": item.get("widthCm", 0), "高(cm)": item.get("heightCm", 0), "备注": item.get("notes", ""),
        })
    return "\ufeff" + output.getvalue()


def candidate_summary(candidate):
    if not candidate:
        return {}
    evaluations = candidate.get("evaluations") or []
    threshold = float(DB.setting("evaluation.threshold", 70))
    confidence = float(DB.setting("evaluation.min_confidence", 70))
    dedupe_status = candidate_dedupe_status(candidate)
    dedupe_reasons = candidate.get("dedupe_reasons") or []
    precheck = candidate_precheck_effective(candidate)
    precheck_status = precheck.get("precheck_status") or "not_checked"
    candidate["dedupeStatus"] = dedupe_status
    candidate["dedupeStatusLabel"] = DEDUPE_STATUS_LABELS.get(dedupe_status, dedupe_status)
    candidate["dedupeReason"] = candidate.get("dedupe_reason") or ""
    candidate["dedupeReasons"] = dedupe_reasons
    candidate["duplicateSkipped"] = candidate_is_duplicate_skipped(candidate)
    candidate["precheckStatus"] = precheck_status
    candidate["precheckStatusLabel"] = PRECHECK_STATUS_LABELS.get(precheck_status, precheck_status)
    candidate["precheckReason"] = precheck.get("precheck_reason") or ""
    candidate["precheckReasons"] = precheck.get("precheck_reasons") or []
    candidate["precheckDetails"] = precheck.get("precheck_details") or {}
    candidate["precheckCheckedAt"] = precheck.get("precheck_checked_at")
    candidate["precheckPersisted"] = bool(precheck.get("persisted"))
    candidate["cleanTitle"] = candidate_clean_title(candidate)
    candidate["displayTitle"] = candidate_display_title(candidate)
    candidate["titleCleanRemovedTerms"] = candidate.get("title_clean_removed_terms") or []
    candidate["titleCleanRiskTerms"] = candidate.get("title_clean_risk_terms") or []
    candidate["titleCleanedAt"] = candidate.get("title_cleaned_at")
    candidate["titleNeedsClean"] = precheck.get("precheck_details", {}).get("titleNeedsClean", False)
    image_status = candidate_image_status(candidate)
    candidate["imageStatus"] = image_status
    candidate["imageStatusLabel"] = IMAGE_STATUS_LABELS.get(image_status, image_status)
    candidate["imageReason"] = candidate.get("image_reason") or ""
    candidate["imageReasons"] = candidate.get("image_reasons") or []
    candidate["imageDetails"] = candidate.get("image_details") or {}
    candidate["imageCheckedAt"] = candidate.get("image_checked_at")
    candidate["localImages"] = candidate.get("local_images") or []
    candidate["imageReady"] = image_status == "image_ready"
    candidate["seaFitStatus"] = precheck.get("sea_fit_status") or ""
    candidate["seasonFitStatus"] = precheck.get("season_fit_status") or ""
    candidate["precheckBlocked"] = precheck_status in PRECHECK_BLOCK_STATUSES and precheck_status != "not_checked"
    candidate["marketSummary"] = candidate_market_summary(candidate)
    candidate["qualifiedMarkets"] = [
        item["market"] for item in evaluations
        if item["total_score"] >= threshold and item["confidence"] >= confidence and not item["hard_blocks"]
    ]
    candidate["bestScore"] = max([item["total_score"] for item in evaluations] or [0])
    candidate["dataCompleteness"] = candidate_data_completeness(candidate)
    candidate["missingFields"] = candidate["dataCompleteness"]["missingFields"]
    candidate["missingHints"] = candidate["dataCompleteness"]["missingHints"]
    candidate["missingFieldCount"] = len(candidate["missingFields"])
    candidate["nextAction"] = candidate["dataCompleteness"]["nextAction"]
    candidate["isReadyToScore"] = candidate["dataCompleteness"]["readyToScore"]
    candidate["canCollect"] = (
        bool(candidate["qualifiedMarkets"])
        and candidate["isReadyToScore"]
        and not candidate_is_skipped(candidate)
        and not candidate["duplicateSkipped"]
        and precheck_status == "precheck_passed"
        and candidate["imageReady"]
    )
    candidate["queue"] = candidate_queue(candidate)
    candidate["workflowStatus"] = get_candidate_workflow_status(candidate)
    return candidate


def workflow_status(stage, blocked=False, failed=False, next_action="", detail=""):
    return {
        "stage": stage,
        "label": WORKFLOW_STAGE_LABELS.get(stage, stage),
        "blocked": bool(blocked),
        "failed": bool(failed),
        "nextAction": next_action,
        "detail": detail,
    }


def get_candidate_workflow_status(candidate):
    if not candidate:
        return workflow_status("candidate_imported", blocked=True, failed=True, detail="候选不存在")
    if candidate_is_duplicate_skipped(candidate):
        return workflow_status("failure_handling", blocked=True, failed=True, next_action="查看重复原因", detail=candidate.get("dedupe_reason") or "重复候选已跳过")
    if candidate_is_skipped(candidate):
        return workflow_status("failure_handling", blocked=True, failed=True, next_action="恢复或删除候选", detail="候选已跳过")
    precheck = candidate_precheck_effective(candidate)
    precheck_status = precheck.get("precheck_status") or "not_checked"
    if precheck_status in ("risk_blocked", "precheck_failed", "low_priority_skipped"):
        failed = precheck_status in ("risk_blocked", "precheck_failed")
        return workflow_status(
            "failure_handling",
            blocked=True,
            failed=failed,
            next_action=PRECHECK_STATUS_LABELS.get(precheck_status, "处理预检"),
            detail=precheck.get("precheck_reason") or "候选预检未通过",
        )
    if precheck_status in ("needs_title_clean", "needs_image_check"):
        return workflow_status(
            "candidate_need_data",
            blocked=True,
            next_action=PRECHECK_STATUS_LABELS.get(precheck_status, "处理预检"),
            detail=precheck.get("precheck_reason") or "候选预检待补",
        )
    completeness = candidate.get("dataCompleteness") or candidate_data_completeness(candidate)
    if not completeness.get("readyToScore"):
        return workflow_status("candidate_need_data", blocked=True, next_action=completeness.get("nextAction") or "补数据", detail="缺失 %d 项必填数据" % len(completeness.get("requiredMissingFields") or []))
    evaluations = candidate.get("evaluations") or []
    if len(evaluations) < len(MARKETS):
        return workflow_status("candidate_ready_to_score", next_action="五国评分")
    market_summary = candidate.get("marketSummary") or candidate_market_summary(candidate)
    if market_summary.get("collectableMarkets"):
        image_status = candidate_image_status(candidate)
        if image_status in ("image_failed", "needs_generation"):
            return workflow_status(
                "image_needs_generation",
                blocked=True,
                failed=image_status == "image_failed",
                next_action=IMAGE_STATUS_LABELS.get(image_status, "处理图片"),
                detail=candidate.get("image_reason") or "图片未达标",
            )
        if image_status in ("image_pending", "original_usable", "needs_cleanup", "image_processing"):
            return workflow_status(
                "image_needs_generation",
                blocked=True,
                next_action="图片自动判断",
                detail=IMAGE_STATUS_LABELS.get(image_status, "图片待处理"),
            )
        return workflow_status("candidate_collectable", next_action="采集达标商品", detail="达标 %d 国" % len(market_summary.get("collectableMarkets") or []))
    return workflow_status("candidate_scored", blocked=True, next_action="人工复核或跳过", detail="无可采集国家")


def candidate_market_summary(candidate):
    evaluations = candidate.get("evaluations") or []
    threshold = float(DB.setting("evaluation.threshold", 70))
    min_confidence = float(DB.setting("evaluation.min_confidence", 70))
    markets = {}
    qualified = []
    review_markets = []
    rejected_markets = []
    blocked_markets = []
    low_confidence_markets = []
    for market in MARKETS:
        evaluation = next((item for item in evaluations if item.get("market") == market), None)
        if not evaluation:
            markets[market] = {
                "status": "missing",
                "decision": "review",
                "decisionLabel": "需人工复核",
                "score": None,
                "confidence": 0,
                "marginPct": None,
                "hasHardBlock": False,
                "hardBlocks": ["未评估"],
                "reason": "尚未生成该国家评分",
                "suggestedAction": "补充目标售价和市场样本后重新评分",
            }
            review_markets.append(market)
            continue
        hard_blocks = list(evaluation.get("hard_blocks") or [])
        score = float(evaluation.get("total_score") or 0)
        confidence = float(evaluation.get("confidence") or 0)
        metrics = evaluation.get("metrics") or {}
        margin = metrics.get("margin_pct")
        reasons = list(evaluation.get("reasons") or [])
        if score >= threshold and confidence >= min_confidence and not hard_blocks:
            status = "qualified"
            decision = "collectable"
            decision_label = "可采集"
            reason = "达到分数和置信度门槛，且无硬拦截"
            suggested_action = "加入达标采集池"
            qualified.append(market)
        elif hard_blocks:
            status = "blocked"
            decision = "rejected"
            decision_label = "不建议采集"
            reason = "；".join(hard_blocks)
            suggested_action = "跳过或更换供应链接"
            blocked_markets.append(market)
            rejected_markets.append(market)
        else:
            status = "low_confidence" if confidence < min_confidence else "unqualified"
            decision = "review"
            decision_label = "需人工复核"
            reason_parts = []
            if score < threshold:
                reason_parts.append("综合分未达到门槛")
            if confidence < min_confidence:
                reason_parts.append("置信度不足")
            if metrics and not metrics.get("market_data_complete"):
                reason_parts.append("市场样本数据缺失")
            if metrics and not metrics.get("target_price_cny"):
                reason_parts.append("缺少目标售价")
            reason = "；".join(reason_parts) or "接近门槛，建议人工复核"
            suggested_action = "补齐目标售价/市场样本后重新评分"
            if confidence < min_confidence:
                low_confidence_markets.append(market)
            review_markets.append(market)
        markets[market] = {
            "status": status,
            "decision": decision,
            "decisionLabel": decision_label,
            "score": round(score, 1),
            "confidence": round(confidence, 1),
            "marginPct": round(float(margin), 2) if margin is not None else None,
            "hasHardBlock": bool(hard_blocks),
            "hardBlocks": hard_blocks,
            "reason": reason,
            "suggestedAction": suggested_action,
            "metrics": metrics,
            "reasons": reasons,
        }
    summary = {
        "markets": markets,
        "qualified": qualified,
        "collectableMarkets": qualified,
        "reviewMarkets": review_markets,
        "rejectedMarkets": rejected_markets,
        "blockedMarkets": blocked_markets,
        "lowConfidenceMarkets": low_confidence_markets,
        "qualifiedCount": len(qualified),
        "reviewCount": len(review_markets),
        "rejectedCount": len(rejected_markets),
        "blockedCount": len(blocked_markets),
        "missingCount": sum(1 for item in markets.values() if item["status"] == "missing"),
        "hasCollectableMarkets": bool(qualified),
        "nextAction": "采集达标商品" if qualified else "继续补数据",
    }
    return summary


def candidate_data_completeness(candidate):
    market_complete, market_missing = candidate_market_data_status(candidate)
    checks = [
        ("title", "商品标题", "缺少标题", "从1688来源补全或手动填写标题", bool(str(candidate.get("title") or "").strip()), True),
        ("category", "类目", "缺少类目", "从来源识别类目，或在补数据弹窗选择类目", bool(str(candidate.get("category") or "").strip()), True),
        ("source_price", "成本价", "缺少成本价", "从来源补全采购价，或手动填写CNY采购价", float(candidate.get("source_price") or 0) > 0, True),
        ("weight_g", "重量", "缺少重量", "从来源补全重量，或按供应商规格填写克重", float(candidate.get("weight_g") or 0) > 0, True),
        ("monthly_sales", "月销量", "缺少销量", "补充1688销量或近期销量样本", int(candidate.get("monthly_sales") or 0) > 0, True),
        ("rating", "供应商评分", "缺少评分", "补充店铺/商品评分", float(candidate.get("rating") or 0) > 0, True),
        ("dispatch_hours", "发货时效", "缺少发货时效", "补充供应商承诺发货小时数", float(candidate.get("dispatch_hours") or 0) > 0, True),
        ("image_count", "图片", "缺少主图", "从来源补全主图/详情图，或确认已有图片", bool(candidate.get("image_count") or candidate.get("images")), True),
        ("sku_complete", "SKU信息", "缺少 SKU", "确认颜色、尺码和SKU规格完整", bool(candidate.get("sku_complete")), True),
        ("market_data", "目标市场数据", "缺少市场样本数据", "补充五国目标售价和市场样本数据", market_complete, False),
    ]
    required_missing = [
        {"field": field, "label": label, "message": message, "hint": hint}
        for field, label, message, hint, ok, required in checks
        if required and not ok
    ]
    missing = [
        {"field": field, "label": label, "message": message, "hint": hint}
        for field, label, message, hint, ok, _required in checks
        if not ok
    ]
    source_fields = {"title", "category", "source_price", "weight_g", "image_count"}
    if not required_missing:
        next_action = "可进入五国评分"
    elif any(item["field"] in source_fields for item in required_missing):
        next_action = "从来源补全"
    else:
        next_action = "人工补数据"
    required_count = sum(1 for _field, _label, _message, _hint, _ok, required in checks if required)
    required_completed = required_count - len(required_missing)
    return {
        "required": required_count,
        "completed": required_completed,
        "percent": round(required_completed / required_count * 100),
        "missingFields": [item["field"] for item in missing],
        "missingHints": missing,
        "requiredMissingFields": [item["field"] for item in required_missing],
        "requiredMissingHints": required_missing,
        "missingRequiredCount": len(required_missing),
        "readyToScore": len(required_missing) == 0 and not candidate_is_skipped(candidate) and not candidate_is_duplicate_skipped(candidate),
        "marketDataComplete": market_complete,
        "marketMissingFields": market_missing,
        "nextAction": next_action,
    }


def candidate_is_skipped(candidate):
    return str(candidate.get("status") or "") == "已跳过"


def candidate_market_data_status(candidate):
    evaluations = candidate.get("evaluations") or []
    missing = []
    if not evaluations:
        return False, ["缺少目标售价", "缺少市场样本数据"]
    for market in MARKETS:
        evaluation = next((item for item in evaluations if item.get("market") == market), None)
        metrics = (evaluation or {}).get("metrics") or {}
        if not metrics.get("target_price_cny"):
            missing.append("%s 缺少目标售价" % market)
        if not metrics.get("market_data_complete"):
            missing.append("%s 缺少市场样本数据" % market)
    return not missing, missing


def candidate_queue(candidate):
    if candidate_is_duplicate_skipped(candidate):
        return "duplicate_skipped"
    if candidate_is_skipped(candidate):
        return "skipped"
    return "ready_to_score" if candidate.get("dataCompleteness", {}).get("readyToScore") else "need_data"


def filter_candidates_by_status(candidates, status):
    if not status:
        return candidates
    summaries = [candidate_summary(item) for item in candidates]
    if status == "need_data":
        return [item for item in summaries if item["queue"] == "need_data"]
    if status == "ready_to_score":
        return [item for item in summaries if item["queue"] == "ready_to_score"]
    if status == "skipped":
        return [item for item in summaries if item["queue"] == "skipped"]
    if status == "new_candidate":
        return [item for item in summaries if item["dedupeStatus"] == "new_candidate"]
    if status == "duplicate_skipped":
        return [item for item in summaries if item["queue"] == "duplicate_skipped"]
    if status in ("precheck_passed", "risk_blocked", "low_priority_skipped"):
        return [item for item in summaries if item["precheckStatus"] == status]
    if status in IMAGE_STATUS_LABELS:
        return [item for item in summaries if item.get("imageStatus") == status]
    return summaries


def candidate_ids_from_payload(payload):
    ids = payload.get("candidateIds") or payload.get("ids") or []
    return [str(item) for item in ids if item]


def run_ids_from_payload(payload):
    ids = payload.get("runIds") or payload.get("run_ids") or payload.get("ids") or []
    return [str(item) for item in ids if str(item or "").strip()]


def bulk_check_candidates(candidate_ids):
    ids = candidate_ids or [item["id"] for item in DB.list_candidates()]
    dedupe_candidates(ids)
    precheck_candidates(ids)
    checked, need_data, ready_to_score, missing = [], [], [], []
    for candidate_id in ids:
        item = DB.get_candidate(candidate_id)
        if not item:
            missing.append({"id": candidate_id, "error": "候选商品不存在"})
            continue
        summary = candidate_summary(item)
        checked.append(summary)
        if summary["isReadyToScore"]:
            ready_to_score.append(summary["id"])
        elif not candidate_is_skipped(summary) and not candidate_is_duplicate_skipped(summary):
            need_data.append(summary["id"])
    return {
        "checked": len(checked),
        "needData": need_data,
        "readyToScore": ready_to_score,
        "missing": missing,
        "items": checked,
    }


def bulk_skip_candidates(candidate_ids):
    ids = candidate_ids or []
    items, missing = [], []
    for candidate_id in ids:
        item = DB.update_candidate(candidate_id, {"status": "已跳过"})
        if item:
            items.append(candidate_summary(item))
        else:
            missing.append({"id": candidate_id, "error": "候选商品不存在"})
    return {"items": items, "missing": missing}


def bulk_delete_candidates(candidate_ids):
    deleted, missing = [], []
    for candidate_id in candidate_ids or []:
        if DB.delete_candidate(candidate_id):
            deleted.append(candidate_id)
        else:
            missing.append({"id": candidate_id, "error": "候选商品不存在"})
    return {"deleted": deleted, "missing": missing}


def history_dedupe_indexes():
    candidates = [candidate_summary(item) for item in DB.list_candidates()]
    products = DB.list_products()
    collection_box_records = DB.list_collection_box_records() if hasattr(DB, "list_collection_box_records") else []
    runs = DB.list_runs()
    def bucket(items, key_func):
        result = {}
        for item in items:
            key = key_func(item)
            if key:
                result.setdefault(key, []).append(item)
        return result
    return {
        "candidate_by_offer": bucket(candidates, lambda item: str(item.get("source_product_id") or "").strip()),
        "candidate_by_url": bucket(candidates, lambda item: normalize_source_url_for_dedupe(item.get("source_url"))),
        "candidate_by_title": bucket(candidates, lambda item: clean_title_for_dedupe(item.get("title"))),
        "candidate_by_image": bucket(candidates, lambda item: image_fingerprint(primary_candidate_image(item))),
        "product_by_offer": {
            str(item.get("sourceProductId") or ""): item
            for item in products
            if str(item.get("sourceProductId") or "").strip()
        },
        "product_by_url": {
            normalize_source_url_for_dedupe(item.get("sourceUrl")): item
            for item in products
            if normalize_source_url_for_dedupe(item.get("sourceUrl"))
        },
        "product_by_title": {
            clean_title_for_dedupe(item.get("title")): item
            for item in products
            if clean_title_for_dedupe(item.get("title"))
        },
        "product_by_image": {
            image_fingerprint(item.get("mainImage") or (item.get("images") or [""])[0]): item
            for item in products
            if image_fingerprint(item.get("mainImage") or (item.get("images") or [""])[0])
        },
        "box_by_offer": {
            str(item.get("offer_id") or ""): item
            for item in collection_box_records
            if str(item.get("offer_id") or "").strip()
        },
        "box_by_url": {
            normalize_source_url_for_dedupe(item.get("source_url")): item
            for item in collection_box_records
            if normalize_source_url_for_dedupe(item.get("source_url"))
        },
        "box_by_title": {
            clean_title_for_dedupe(item.get("clean_title")): item
            for item in collection_box_records
            if clean_title_for_dedupe(item.get("clean_title"))
        },
        "box_by_image": {
            image_fingerprint(item.get("image_status")): item
            for item in collection_box_records
            if image_fingerprint(item.get("image_status"))
        },
        "run_by_url": {
            normalize_source_url_for_dedupe((run.get("context") or {}).get("url") or run.get("context", {}).get("sourceUrl") or ""): run
            for run in runs
            if run.get("kind") in ("collection", "keyword_search")
            and normalize_source_url_for_dedupe((run.get("context") or {}).get("url") or run.get("context", {}).get("sourceUrl") or "")
        },
        "run_by_offer": {
            str((run.get("context") or {}).get("sourceProductId") or run.get("candidate_id") or ""): run
            for run in runs
            if run.get("kind") in ("collection", "keyword_search")
            and str((run.get("context") or {}).get("sourceProductId") or run.get("candidate_id") or "").strip()
        },
    }


def analyze_candidate_dedupe(candidate, indexes=None):
    indexes = indexes or history_dedupe_indexes()
    reasons = []
    details = []
    candidate_id = candidate.get("id") or ""
    source_url = candidate.get("source_url") or ""
    offer_id = str(candidate.get("source_product_id") or "").strip()
    title_key = clean_title_for_dedupe(candidate.get("title"))
    image_key = image_fingerprint(primary_candidate_image(candidate))
    url_key = normalize_source_url_for_dedupe(source_url)
    def other_candidate(index, key):
        value = index.get(key) if key else None
        if isinstance(value, list):
            return next((item for item in value if item.get("id") != candidate_id), None)
        return value if value and value.get("id") != candidate_id else None
    def similar_title(index):
        if not title_key or len(title_key) < 8:
            return None
        for key, value in index.items():
            if not key or key == title_key:
                continue
            items = value if isinstance(value, list) else [value]
            item = next((row for row in items if row and row.get("id") != candidate_id), None)
            if not item:
                continue
            ratio = SequenceMatcher(None, title_key, key).ratio()
            overlap = title_key in key or key in title_key
            if ratio >= 0.92 or (overlap and min(len(title_key), len(key)) / max(len(title_key), len(key)) >= 0.8):
                return item
        return None
    if offer_id and other_candidate(indexes["candidate_by_offer"], offer_id):
        reasons.append("duplicate_offer_id")
        details.append("已存在同 offer_id 候选")
    elif offer_id and offer_id in indexes["product_by_offer"]:
        reasons.append("duplicate_offer_id")
        details.append("已存在同 offer_id 正式商品")
    elif offer_id and offer_id in indexes["box_by_offer"]:
        reasons.append("already_collected_to_box")
        details.append("已进入妙手采集箱")
    if url_key and other_candidate(indexes["candidate_by_url"], url_key):
        reasons.append("duplicate_url")
        details.append("已存在同链接候选")
    elif url_key and url_key in indexes["product_by_url"]:
        reasons.append("duplicate_url")
        details.append("已存在同链接正式商品")
    elif url_key and url_key in indexes["box_by_url"]:
        reasons.append("already_collected_to_box")
        details.append("已进入妙手采集箱")
    if title_key and other_candidate(indexes["candidate_by_title"], title_key):
        reasons.append("duplicate_title")
        details.append("标题与历史候选高度相似")
    elif title_key and title_key in indexes["product_by_title"]:
        reasons.append("duplicate_title")
        details.append("标题与正式商品相似")
    elif title_key and title_key in indexes["box_by_title"]:
        reasons.append("already_collected_to_box")
        details.append("标题与采集箱记录相似")
    if image_key and other_candidate(indexes["candidate_by_image"], image_key):
        reasons.append("duplicate_image")
        details.append("主图与历史候选重复")
    elif image_key and image_key in indexes["product_by_image"]:
        reasons.append("duplicate_image")
        details.append("主图与正式商品重复")
    elif image_key and image_key in indexes["box_by_image"]:
        reasons.append("duplicate_image")
        details.append("主图与采集箱记录重复")
    if offer_id and offer_id in indexes["run_by_offer"]:
        reasons.append("already_collected_to_box")
        details.append("历史任务中已出现相同商品")
    if url_key and url_key in indexes["run_by_url"]:
        reasons.append("already_collected_to_box")
        details.append("历史任务中已出现相同链接")
    if not reasons:
        if similar_title(indexes["candidate_by_title"]):
            reasons.append("needs_manual_duplicate_check")
            details.append("标题与历史候选高度相似")
        elif similar_title(indexes["product_by_title"]):
            reasons.append("needs_manual_duplicate_check")
            details.append("标题与正式商品高度相似")
        elif similar_title(indexes["box_by_title"]):
            reasons.append("needs_manual_duplicate_check")
            details.append("标题与采集箱记录高度相似")
    reasons = list(dict.fromkeys(reasons))
    dedupe_status = "new_candidate"
    if "already_collected_to_box" in reasons:
        dedupe_status = "already_collected_to_box"
    elif "duplicate_offer_id" in reasons:
        dedupe_status = "duplicate_offer_id"
    elif "duplicate_url" in reasons:
        dedupe_status = "duplicate_url"
    elif "duplicate_image" in reasons:
        dedupe_status = "duplicate_image"
    elif "duplicate_title" in reasons:
        dedupe_status = "duplicate_title"
    elif "needs_manual_duplicate_check" in reasons:
        dedupe_status = "needs_manual_duplicate_check"
    if reasons and dedupe_status == "new_candidate":
        dedupe_status = "needs_manual_duplicate_check"
    return {
        "dedupe_status": dedupe_status,
        "dedupe_reason": "；".join(dict.fromkeys(details)) if details else "",
        "dedupe_reasons": reasons,
        "skip": dedupe_status in DEDUPE_SKIP_STATUSES,
    }


def dedupe_candidates(candidate_ids=None):
    ids = candidate_ids or [item["id"] for item in DB.list_candidates()]
    indexes = history_dedupe_indexes()
    results = []
    skipped = []
    needs_manual = []
    for candidate_id in ids:
        candidate = DB.get_candidate(candidate_id)
        if not candidate:
            continue
        analysis = analyze_candidate_dedupe(candidate, indexes)
        updated = DB.update_candidate(candidate_id, {
            "dedupe_status": analysis["dedupe_status"],
            "dedupe_reason": analysis["dedupe_reason"],
            "dedupe_reasons": analysis["dedupe_reasons"],
            "dedupe_checked_at": int(time.time()),
        })
        summary = candidate_summary(updated)
        results.append(summary)
        if analysis["skip"]:
            skipped.append({
                "id": candidate_id,
                "title": summary.get("title") or summary.get("source_product_id") or candidate_id,
                "dedupeStatus": analysis["dedupe_status"],
                "dedupeReason": analysis["dedupe_reason"],
                "dedupeReasons": analysis["dedupe_reasons"],
                "error": analysis["dedupe_reason"] or DEDUPE_STATUS_LABELS.get(analysis["dedupe_status"], analysis["dedupe_status"]),
            })
        elif analysis["dedupe_status"] == "needs_manual_duplicate_check":
            needs_manual.append({
                "id": candidate_id,
                "title": summary.get("title") or summary.get("source_product_id") or candidate_id,
                "dedupeStatus": analysis["dedupe_status"],
                "dedupeReason": analysis["dedupe_reason"],
                "dedupeReasons": analysis["dedupe_reasons"],
                "error": analysis["dedupe_reason"] or "疑似重复，需要人工确认",
            })
    return {"items": results, "skipped": skipped, "needsManual": needs_manual}


def collect_qualified_candidates(candidate_ids, markets=None, review=False):
    threshold = float(DB.setting("evaluation.threshold", 70))
    confidence = float(DB.setting("evaluation.min_confidence", 70))
    requested = set(candidate_ids or [])
    requested_markets = {str(item).upper() for item in (markets or []) if str(item).upper() in MARKETS}
    runs, blocked = [], []
    for candidate in DB.list_candidates():
        if requested and candidate["id"] not in requested:
            continue
        summary = candidate_summary(candidate)
        if summary.get("duplicateSkipped"):
            blocked.append({
                "id": candidate["id"],
                "title": summary.get("title") or summary.get("source_product_id") or candidate["id"],
                "dedupeStatus": summary.get("dedupeStatus"),
                "dedupeReason": summary.get("dedupeReason"),
                "error": "重复候选已跳过，不进入自动采集",
            })
            continue
        if not summary.get("cleanTitle"):
            try:
                clean_candidate_title(candidate["id"])
                candidate = DB.get_candidate(candidate["id"])
                summary = candidate_summary(candidate)
            except Exception as exc:
                blocked.append({
                    "id": candidate["id"],
                    "title": summary.get("title") or summary.get("source_product_id") or candidate["id"],
                    "precheckStatus": summary.get("precheckStatus") or "needs_title_clean",
                    "precheckReason": summary.get("precheckReason") or "",
                    "error": str(exc),
                })
                continue
        precheck_result = precheck_candidates([candidate["id"]])
        prechecked = (precheck_result.get("items") or [{}])[0]
        precheck_status = prechecked.get("precheckStatus") or "not_checked"
        precheck_reason = prechecked.get("precheckReason") or ""
        if precheck_status != "precheck_passed":
            incomplete_basic = not summary["isReadyToScore"]
            blocked.append({
                "id": candidate["id"],
                "title": prechecked.get("title") or summary.get("title") or summary.get("source_product_id") or candidate["id"],
                "precheckStatus": precheck_status,
                "precheckStatusLabel": prechecked.get("precheckStatusLabel") or PRECHECK_STATUS_LABELS.get(precheck_status, precheck_status),
                "precheckReason": precheck_reason,
                "precheckReasons": prechecked.get("precheckReasons") or [],
                "precheckDetails": prechecked.get("precheckDetails") or {},
                "missingFields": summary.get("dataCompleteness", {}).get("requiredMissingFields") or [],
                "missingHints": summary.get("dataCompleteness", {}).get("requiredMissingHints") or [],
                "error": "基础数据不完整，不能进入自动采集" if incomplete_basic else (precheck_reason or "商品预检未通过，不进入自动采集"),
            })
            continue
        if not summary["isReadyToScore"]:
            blocked.append({
                "id": candidate["id"],
                "title": summary.get("title") or summary.get("source_product_id") or candidate["id"],
                "missingFields": summary.get("dataCompleteness", {}).get("requiredMissingFields") or [],
                "missingHints": summary.get("dataCompleteness", {}).get("requiredMissingHints") or [],
                "precheckStatus": precheck_status,
                "precheckStatusLabel": prechecked.get("precheckStatusLabel") or PRECHECK_STATUS_LABELS.get(precheck_status, precheck_status),
                "precheckReason": precheck_reason,
                "precheckReasons": prechecked.get("precheckReasons") or [],
                "error": "基础数据不完整，不能进入自动采集",
            })
            continue
        candidate = DB.get_candidate(candidate["id"])
        summary = candidate_summary(candidate)
        if not summary.get("imageReady"):
            image_result = auto_process_candidate_images([candidate["id"]])
            candidate = DB.get_candidate(candidate["id"])
            summary = candidate_summary(candidate)
            if not summary.get("imageReady"):
                result_item = (image_result.get("items") or [{}])[0]
                blocked.append({
                    "id": candidate["id"],
                    "title": summary.get("title") or summary.get("source_product_id") or candidate["id"],
                    "imageStatus": summary.get("imageStatus"),
                    "imageStatusLabel": summary.get("imageStatusLabel"),
                    "imageReason": summary.get("imageReason") or "",
                    "imageReasons": summary.get("imageReasons") or result_item.get("reasons") or [],
                    "imageDetails": summary.get("imageDetails") or result_item.get("details") or {},
                    "error": "图片未达标，不能进入妙手采集箱",
                })
                continue
        candidate = DB.get_candidate(candidate["id"])
        summary = candidate_summary(candidate)
        collectable_markets = [
            item["market"] for item in candidate["evaluations"]
            if item["total_score"] >= threshold and item["confidence"] >= confidence and not item["hard_blocks"]
        ]
        if requested_markets:
            collectable_markets = [market for market in collectable_markets if market in requested_markets]
        if review:
            DB.update_candidate(candidate["id"], {"status": "人工复核"})
            blocked.append({
                "id": candidate["id"],
                "title": summary.get("title") or summary.get("source_product_id") or candidate["id"],
                "markets": summary["marketSummary"].get("reviewMarkets") or [],
                "error": "已转人工复核",
            })
            continue
        if not collectable_markets:
            continue
        duplicate = DB.row("SELECT id FROM automation_runs WHERE candidate_id=? AND kind='collection' AND status NOT IN ('failed','blocked')", (candidate["id"],))
        if duplicate:
            continue
        DB.update_candidate(candidate["id"], {
            "status": "插件采集中",
            "collection_channel": "plugin_first",
        })
        run = AUTOMATION.create_collection_run(candidate)
        context = {**(run.get("context") or {}), "markets": collectable_markets}
        DB.update_run(run["id"], context=context)
        enqueue_automation_run(run["id"])
        refreshed = DB.get_run(run["id"])
        refreshed["markets"] = collectable_markets
        runs.append(refreshed)
    return {"items": runs, "blocked": blocked}


def qualified_evaluations_summary():
    items = []
    for candidate in DB.list_candidates():
        summary = candidate_summary(candidate)
        collectable = summary["marketSummary"].get("collectableMarkets") or []
        if not collectable or summary.get("precheckStatus") != "precheck_passed":
            continue
        items.append({
            "id": summary["id"],
            "title": summary.get("title") or "1688商品 %s" % (summary.get("source_product_id") or ""),
            "sourceUrl": summary.get("source_url") or "",
            "sourceProductId": summary.get("source_product_id") or "",
            "collectableMarkets": collectable,
            "reviewMarkets": summary["marketSummary"].get("reviewMarkets") or [],
            "rejectedMarkets": summary["marketSummary"].get("rejectedMarkets") or [],
            "markets": summary["marketSummary"].get("markets") or {},
            "canCollect": summary["canCollect"],
            "precheckStatus": summary.get("precheckStatus"),
            "precheckReason": summary.get("precheckReason"),
            "reason": "、".join(collectable) + " 达到采集门槛，预检通过",
        })
    return {"items": items, "count": len(items)}


def recalculate_evaluations(candidate_ids):
    return evaluate_candidates(candidate_ids)


def workflow_step(key, name, pending=0, done=0, failed=0, blocked=False, action=""):
    return {
        "key": key,
        "name": name,
        "pending": int(pending or 0),
        "done": int(done or 0),
        "failed": int(failed or 0),
        "blocked": bool(blocked),
        "action": action,
    }


def approved_asset_product_ids():
    return {
        row["product_id"]
        for row in DB.rows("SELECT DISTINCT product_id FROM assets WHERE approved=1 AND review_status!='rejected'")
    }


def workflow_summary():
    candidates = [candidate_summary(item) for item in DB.list_candidates()]
    products = DB.list_products()
    batches = DB.rows("SELECT * FROM batches")
    runs = DB.rows("SELECT * FROM automation_runs")
    generation_jobs = DB.rows("SELECT * FROM generation_jobs")
    approved_product_ids = approved_asset_product_ids()
    publish_keys = DB.rows("SELECT * FROM publish_keys")
    threshold = float(DB.setting("evaluation.threshold", 70))
    min_confidence = float(DB.setting("evaluation.min_confidence", 70))

    candidate_count = len(candidates)
    product_count = len(products)
    completed_data = sum(
        1 for item in candidates
        if item.get("category")
        and float(item.get("source_price") or 0) > 0
        and float(item.get("weight_g") or 0) > 0
        and int(item.get("monthly_sales") or 0) > 0
        and float(item.get("rating") or 0) > 0
        and item.get("sku_complete")
    )
    fully_evaluated = sum(1 for item in candidates if len(item.get("evaluations") or []) >= len(MARKETS))
    evaluation_failed = sum(
        1 for item in candidates
        if any((evaluation.get("hard_blocks") or []) or float(evaluation.get("confidence") or 0) < min_confidence for evaluation in item.get("evaluations") or [])
    )
    qualified = sum(
        1 for item in candidates
        if any(
            evaluation.get("total_score", 0) >= threshold
            and evaluation.get("confidence", 0) >= min_confidence
            and not evaluation.get("hard_blocks")
            for evaluation in item.get("evaluations") or []
        )
    )
    collected_candidates = sum(1 for item in candidates if item.get("collected_at"))
    collection_failed = sum(1 for item in runs if item.get("kind") == "collection" and item.get("status") in ("failed", "blocked"))

    image_pending_statuses = {"queued", "running", "preparing"}
    image_done_statuses = {"awaiting_approval", "completed"}
    image_pending = sum(1 for item in generation_jobs if item.get("status") in image_pending_statuses)
    image_done = sum(1 for item in generation_jobs if item.get("status") in image_done_statuses)
    image_failed = sum(1 for item in generation_jobs if item.get("status") == "failed")

    approved_products = sum(1 for item in products if item["id"] in approved_product_ids)
    products_missing_approval = max(0, product_count - approved_products)
    eligible_for_batch = approved_products
    failed_batches = sum(1 for item in batches if item.get("status") in ("failed", "blocked"))

    dry_batches = [item for item in batches if item.get("dry_run")]
    live_batches = [item for item in batches if not item.get("dry_run")]
    dry_run_done = sum(1 for item in dry_batches if item.get("status") in ("completed", "confirmed"))
    dry_run_pending = sum(1 for item in dry_batches if item.get("status") in ("draft", "preparing", "confirmed"))
    dry_run_failed = sum(1 for item in dry_batches if item.get("status") in ("failed", "blocked"))

    live_done = sum(1 for item in publish_keys if item.get("status") == "published")
    live_pending = sum(1 for item in live_batches if item.get("status") in ("draft", "preparing", "confirmed"))
    live_failed = sum(1 for item in live_batches if item.get("status") in ("failed", "blocked"))

    running_statuses = {"queued", "running", "preparing", "waiting_browser", "waiting_for_manual", "waiting_confirmation"}
    run_pending = sum(1 for item in runs if item.get("status") in running_statuses)
    run_done = sum(1 for item in runs if item.get("status") == "completed")
    run_failed = len(publish_results_summary()["failures"])

    steps = [
        workflow_step(
            "import_candidates", "导入候选商品", done=candidate_count,
            blocked=False, action="导入候选",
        ),
        workflow_step(
            "complete_product_data", "补全商品基础数据",
            pending=max(0, candidate_count - completed_data), done=completed_data,
            blocked=candidate_count > 0 and completed_data < candidate_count, action="补数据",
        ),
        workflow_step(
            "five_market_scoring", "五国选品评分",
            pending=max(0, candidate_count - fully_evaluated), done=fully_evaluated,
            failed=evaluation_failed,
            blocked=candidate_count > 0 and (fully_evaluated < candidate_count or evaluation_failed > 0),
            action="五国评分",
        ),
        workflow_step(
            "collect_qualified", "采集达标商品",
            pending=max(0, qualified - collected_candidates - product_count),
            done=product_count or collected_candidates,
            failed=collection_failed,
            blocked=qualified > 0 and (collection_failed > 0 or product_count == 0 or any(not item.get("imageReady") for item in candidates if item.get("qualifiedMarkets"))),
            action="采集达标",
        ),
        workflow_step(
            "generate_images", "AI 生成商品图片",
            pending=image_pending, done=image_done, failed=image_failed,
            blocked=product_count > 0 and (image_pending > 0 or image_failed > 0),
            action="生成图片",
        ),
        workflow_step(
            "review_images", "图片审核与确认",
            pending=products_missing_approval, done=approved_products,
            blocked=product_count > 0 and products_missing_approval > 0,
            action="审核图片",
        ),
        workflow_step(
            "create_batches", "创建铺货批次",
            pending=max(0, eligible_for_batch - len(batches)), done=len(batches), failed=failed_batches,
            blocked=eligible_for_batch > 0 and (len(batches) == 0 or failed_batches > 0),
            action="创建批次",
        ),
        workflow_step(
            "dry_run_check", "演练模式检查",
            pending=dry_run_pending, done=dry_run_done, failed=dry_run_failed,
            blocked=bool(dry_batches) and (dry_run_pending > 0 or dry_run_failed > 0),
            action="演练检查",
        ),
        workflow_step(
            "live_confirm", "真实发布确认",
            pending=live_pending, done=live_done, failed=live_failed,
            blocked=bool(live_batches) and (live_pending > 0 or live_failed > 0),
            action="发布确认",
        ),
        workflow_step(
            "publish_results", "发布结果与失败处理",
            pending=run_pending, done=run_done, failed=run_failed,
            blocked=run_pending > 0 or run_failed > 0,
            action="查看失败",
        ),
    ]
    return {"steps": steps}


def latest_job_for_product(jobs, product_id):
    product_jobs = [item for item in jobs if item.get("product_id") == product_id]
    if not product_jobs:
        return None
    return sorted(product_jobs, key=lambda item: item.get("created_at") or 0, reverse=True)[0]


def image_failure_guidance(error):
    message = str(error or "").strip()
    if not message:
        return ["查看图片中转站配置后重试"]
    if "Base URL" in message or "API Key" in message or "中转站" in message:
        return ["到系统设置补全图片中转站 Base URL 和 API Key", "保存后重试生图任务"]
    if "主图" in message or "图片" in message or "目标链接" in message:
        return ["上传可用主图或重新从来源补全图片", "确认图片能打开后重试"]
    if "超时" in message or "timeout" in message.lower():
        return ["提高图片接口超时时间", "确认中转站任务状态接口可用后重试"]
    return ["检查错误信息对应的图片接口或素材问题", "修复后点击重试"]


def asset_review_status(asset):
    status = str((asset or {}).get("review_status") or "").strip()
    if status:
        return status
    return "approved" if (asset or {}).get("approved") else "pending"


def product_image_summary(product, assets, jobs):
    product_id = product["id"]
    product_assets = [item for item in assets if item.get("product_id") == product_id]
    approved = [item for item in product_assets if item.get("approved") and asset_review_status(item) == "approved"]
    rejected = [item for item in product_assets if asset_review_status(item) == "rejected"]
    pending_assets = [item for item in product_assets if not item.get("approved") and asset_review_status(item) != "rejected"]
    generated = [item for item in product_assets if item.get("kind") == "generated"]
    uploaded = [item for item in product_assets if item.get("kind") == "uploaded"]
    latest_job = latest_job_for_product(jobs, product_id)
    job_status = latest_job.get("status") if latest_job else ""
    source_images = product.get("images") if isinstance(product.get("images"), list) else []
    source_image_count = len([item for item in source_images if item]) or (1 if product.get("mainImage") else 0)
    minimum_required = 1
    has_source_image = source_image_count > 0
    meets_minimum = len(approved) >= minimum_required
    status = "needs_generation"
    action = "AI生图"
    if meets_minimum:
        status = "approved"
        action = "查看图片"
    elif job_status in ("queued", "running", "preparing"):
        status = "generating"
        action = "查看进度"
    elif job_status == "failed":
        status = "generation_failed"
        action = "重试生图"
    elif pending_assets or job_status == "awaiting_approval":
        status = "awaiting_approval"
        action = "审核图片"
    elif generated and not pending_assets:
        status = "rejected" if rejected else "generation_success"
        action = "重新生成" if rejected else "审核图片"
    elif not has_source_image:
        status = "missing_source_image"
        action = "上传图片"
    queue = "needs_generation" if status == "missing_source_image" else status
    return {
        "productId": product_id,
        "title": product.get("title") or "",
        "status": status,
        "queue": queue,
        "action": action,
        "hasSourceImage": has_source_image,
        "sourceImageCount": source_image_count,
        "approvedCount": len(approved),
        "pendingReviewCount": len(pending_assets),
        "rejectedCount": len(rejected),
        "generatedCount": len(generated),
        "uploadedCount": len(uploaded),
        "assetCount": len(product_assets),
        "minimumRequired": minimum_required,
        "meetsMinimumImages": meets_minimum,
        "latestJob": latest_job,
        "failure": {
            "error": (latest_job or {}).get("error") or "",
            "failedApi": (latest_job or {}).get("failed_api") or "",
            "model": (latest_job or {}).get("model") or "",
            "prompt": (latest_job or {}).get("last_prompt") or "",
            "attempts": (latest_job or {}).get("attempts") or 0,
            "lastRunAt": (latest_job or {}).get("last_run_at"),
            "suggestedActions": image_failure_guidance((latest_job or {}).get("error")),
        } if job_status == "failed" else None,
    }


def image_workbench_summary():
    products = DB.list_products()
    assets = DB.rows("SELECT * FROM assets ORDER BY created_at")
    jobs = DB.rows("SELECT * FROM generation_jobs ORDER BY created_at DESC")
    items = [product_image_summary(product, assets, jobs) for product in products]
    overview = {
        "totalProducts": len(products),
        "needsGeneration": sum(1 for item in items if item["queue"] == "needs_generation"),
        "generating": sum(1 for item in items if item["status"] == "generating"),
        "generationSuccess": sum(1 for item in items if item["status"] == "generation_success"),
        "awaitingApproval": sum(1 for item in items if item["status"] == "awaiting_approval"),
        "approved": sum(1 for item in items if item["status"] == "approved"),
        "failed": sum(1 for item in items if item["status"] == "generation_failed"),
        "rejected": sum(1 for item in items if item["status"] == "rejected"),
        "meetsMinimum": sum(1 for item in items if item["meetsMinimumImages"]),
        "missingMinimum": sum(1 for item in items if not item["meetsMinimumImages"]),
    }
    queues = [
        {
            "key": key,
            "name": name,
            "count": sum(1 for item in items if item["queue"] == key),
        }
        for key, name in IMAGE_QUEUE_DEFINITIONS
    ]
    return {"overview": overview, "queues": queues, "items": items, "rejectionReasons": REJECTION_REASONS}


def get_product_workflow_status(product_id):
    product = DB.get_product(product_id)
    if not product:
        return workflow_status("failure_handling", blocked=True, failed=True, detail="商品不存在")
    batches = [item for item in DB.rows("SELECT * FROM batches ORDER BY updated_at DESC") if product_id in (item.get("product_ids") or [])]
    batch_ids = {item["id"] for item in batches}
    failures = [
        item for item in publish_results_summary()["failures"]
        if item.get("productId") == product_id or item.get("batchId") in batch_ids
    ]
    if failures:
        return workflow_status("failure_handling", blocked=True, failed=True, next_action="处理失败任务", detail=failures[0].get("reason") or failures[0].get("type"))
    assets = DB.rows("SELECT * FROM assets WHERE product_id=? ORDER BY created_at", (product_id,))
    jobs = DB.rows("SELECT * FROM generation_jobs WHERE product_id=? ORDER BY created_at DESC", (product_id,))
    image_status = product_image_summary(product, assets, jobs)
    if image_status["status"] in ("generation_failed", "rejected"):
        detail = (image_status.get("failure") or {}).get("error") or image_status.get("status")
        return workflow_status("failure_handling", blocked=True, failed=True, next_action=image_status.get("action") or "处理图片失败", detail=detail)
    if image_status["status"] == "generating":
        return workflow_status("image_generating", next_action="查看进度")
    if image_status["status"] in ("needs_generation", "missing_source_image"):
        return workflow_status("image_needs_generation", blocked=True, next_action=image_status.get("action") or "AI生图")
    if image_status["status"] in ("awaiting_approval", "generation_success"):
        return workflow_status("image_awaiting_review", blocked=True, next_action="审核图片")
    if not image_status["meetsMinimumImages"]:
        return workflow_status("image_awaiting_review", blocked=True, next_action="审核图片", detail="未达到铺货最低图片要求")
    publish_keys = [item for item in DB.rows("SELECT * FROM publish_keys WHERE product_id=?", (product_id,))]
    if any(item.get("status") == "published" for item in publish_keys):
        return workflow_status("publish_completed", next_action="查看发布结果")
    if any(item.get("status") in ("failed", "blocked", "duplicate", "skipped") for item in publish_keys):
        return workflow_status("failure_handling", blocked=True, failed=True, next_action="处理发布失败")
    if any(not item.get("dry_run") and item.get("status") in ("confirmed", "preparing") for item in batches):
        return workflow_status("live_publishing", next_action="查看自动化任务")
    if any(item.get("dry_run") and item.get("status") == "completed_dry_run" for item in batches):
        return workflow_status("dry_run_passed", next_action="创建真实发布批次")
    if batches:
        return workflow_status("batch_precheck", next_action="准备/演练批次")
    return workflow_status("ready_to_batch", next_action="创建铺货批次")


def products_with_workflow_status():
    return [{**product, "workflowStatus": get_product_workflow_status(product["id"])} for product in DB.list_products()]


def collection_queue_status(run):
    status = run.get("status") or "queued"
    resolution = run.get("resolution") or ""
    if resolution == "manual" or status in ("manual", "awaiting_claim", "ready_for_live"):
        return "manual"
    if status in ("queued", "preparing", "waiting_browser", "waiting_for_manual"):
        return "pending"
    if status == "running":
        return "running"
    if status == "completed":
        return "completed"
    if status in ("failed", "blocked"):
        return "failed"
    if status in ("skipped", "handled"):
        return "manual"
    return "pending"


def collection_queue_item_from_run(run, candidates_by_id=None):
    candidates_by_id = candidates_by_id or {}
    status = run.get("status") or ""
    candidate = candidates_by_id.get(run.get("candidate_id") or "") or DB.get_candidate(run.get("candidate_id") or "")
    diagnostics = run.get("diagnostics") or {}
    context = run.get("context") or {}
    queue = collection_queue_status(run)
    title = (candidate or {}).get("title") or (candidate or {}).get("source_product_id") or "未命名候选"
    return {
        "id": run["id"],
        "source": "automation_run",
        "queue": queue,
        "queueLabel": dict(COLLECTION_QUEUE_DEFINITIONS).get(queue, queue),
        "candidateId": run.get("candidate_id") or "",
        "product": title,
        "title": title,
        "sourceUrl": (candidate or {}).get("source_url") or "",
        "sourceProductId": (candidate or {}).get("source_product_id") or "",
        "markets": context.get("markets") or [],
        "market": "、".join(context.get("markets") or []) or "",
        "currentStep": diagnostics.get("failedStep") or run.get("current_step") or ("等待采集" if queue == "pending" else ""),
        "status": run.get("status") or "",
        "statusLabel": dict(COLLECTION_QUEUE_DEFINITIONS).get(queue, queue),
        "reason": diagnostics.get("error") or run.get("error") or "",
        "error": diagnostics.get("error") or run.get("error") or "",
        "attempts": int(run.get("attempts") or 0),
        "lastRunAt": run.get("updated_at") or run.get("created_at"),
        "screenshot": diagnostics.get("screenshot") or run.get("screenshot") or "",
        "currentUrl": diagnostics.get("currentUrl") or "",
        "clickableText": diagnostics.get("clickableText") or [],
        "suggestedActions": diagnostics.get("suggestedActions") or (["检查妙手插件、登录状态和采集按钮文本后重试"] if queue == "failed" else []),
        "context": context,
        "resolution": run.get("resolution") or "",
        "canRetry": (queue in ("failed", "pending") or status == "waiting_for_manual") and int(run.get("attempts") or 0) < 2,
        "canSkip": queue in ("pending", "failed", "manual"),
        "canManual": queue in ("pending", "running", "failed"),
    }


def collection_queue_summary(status=""):
    status = str(status or "").strip()
    candidates = {item["id"]: candidate_summary(item) for item in DB.list_candidates()}
    collected_candidate_ids = {
        product.get("candidateId")
        for product in DB.list_products()
        if product.get("candidateId")
    }
    runs = [run for run in DB.list_runs() if run.get("kind") == "collection"]
    existing_candidate_ids = {run.get("candidate_id") for run in runs if run.get("candidate_id")}
    items = [collection_queue_item_from_run(run, candidates) for run in runs]
    for candidate in candidates.values():
        if (
            not candidate.get("canCollect")
            or candidate["id"] in existing_candidate_ids
            or candidate["id"] in collected_candidate_ids
            or candidate.get("collected_at")
            or candidate.get("duplicateSkipped")
        ):
            continue
        collectable = candidate.get("marketSummary", {}).get("collectableMarkets") or candidate.get("qualifiedMarkets") or []
        items.append({
            "id": "candidate:" + candidate["id"],
            "source": "candidate",
            "queue": "pending",
            "queueLabel": "待采集",
            "candidateId": candidate["id"],
            "product": candidate.get("title") or candidate.get("source_product_id") or "未命名候选",
            "title": candidate.get("title") or candidate.get("source_product_id") or "未命名候选",
            "sourceUrl": candidate.get("source_url") or "",
            "sourceProductId": candidate.get("source_product_id") or "",
            "markets": collectable,
            "market": "、".join(collectable),
            "currentStep": "等待创建采集任务",
            "status": "ready_to_collect",
            "statusLabel": "待采集",
            "reason": "",
            "error": "",
            "attempts": 0,
            "lastRunAt": candidate.get("updated_at") or candidate.get("created_at"),
            "screenshot": "",
            "currentUrl": "",
            "clickableText": [],
            "suggestedActions": ["点击开始采集后进入妙手插件任务队列"],
            "context": {"markets": collectable},
            "resolution": "",
            "canRetry": False,
            "canSkip": True,
            "canManual": True,
        })
    counts = {key: 0 for key, _ in COLLECTION_QUEUE_DEFINITIONS}
    for item in items:
        counts[item["queue"]] = counts.get(item["queue"], 0) + 1
    filtered = [item for item in items if not status or item["queue"] == status]
    filtered.sort(key=lambda item: (item.get("lastRunAt") or 0, item.get("product") or ""), reverse=True)
    return {
        "queues": [{"key": key, "name": name, "count": counts.get(key, 0)} for key, name in COLLECTION_QUEUE_DEFINITIONS],
        "items": filtered,
        "count": len(filtered),
    }


def dedupe_queue_summary(status=""):
    status = str(status or "").strip()
    items = [candidate_summary(item) for item in DB.list_candidates()]
    if status == "new_candidate":
        items = [item for item in items if item.get("dedupeStatus") == "new_candidate"]
    elif status == "duplicate_skipped":
        items = [item for item in items if item.get("queue") == "duplicate_skipped"]
    elif status:
        items = [item for item in items if item.get("dedupeStatus") == status]
    items.sort(key=lambda item: (item.get("dedupe_checked_at") or 0, item.get("created_at") or 0), reverse=True)
    counts = {key: 0 for key in DEDUPE_STATUS_LABELS}
    for item in DB.list_candidates():
        counts[candidate_dedupe_status(item)] = counts.get(candidate_dedupe_status(item), 0) + 1
    return {
        "queues": [
            {"key": key, "name": name, "count": counts.get(key, 0)}
            for key, name in DEDUPE_STATUS_LABELS.items()
        ],
        "items": items,
        "count": len(items),
    }


def collection_task_detail(task_id):
    task_id = str(task_id or "")
    if task_id.startswith("candidate:"):
        candidate_id = task_id.split(":", 1)[1]
        candidate = DB.get_candidate(candidate_id)
        if not candidate:
            raise ValueError("采集候选不存在")
        summary = candidate_summary(candidate)
        item = next((row for row in collection_queue_summary("pending")["items"] if row["id"] == task_id), None)
        return item or {
            "id": task_id,
            "source": "candidate",
            "queue": "pending",
            "candidateId": candidate_id,
            "product": summary.get("title") or summary.get("source_product_id") or "未命名候选",
            "sourceUrl": summary.get("source_url") or "",
            "markets": summary.get("marketSummary", {}).get("collectableMarkets") or [],
            "suggestedActions": ["点击开始采集后进入妙手插件任务队列"],
        }
    run = DB.get_run(task_id)
    if not run or run.get("kind") != "collection":
        raise ValueError("采集任务不存在")
    return collection_queue_item_from_run(run)


def retry_collection_run(run):
    if int(run["attempts"] or 0) >= 2:
        raise ValueError("该采集任务已达到最多2次重试限制，请检查页面或配置后新建任务")
    DB.update_run(run["id"], status="queued", error="", attempts=int(run["attempts"] or 0) + 1, resolution="")
    enqueue_automation_run(run["id"])
    return DB.get_run(run["id"])


def bulk_collection_action(payload):
    action = str(payload.get("action") or "").strip()
    if action not in ("start", "retry_failed", "skip", "manual"):
        raise ValueError("采集批量操作无效")
    candidate_ids = candidate_ids_from_payload(payload)
    run_ids = run_ids_from_payload(payload)
    if not candidate_ids and not run_ids:
        status = "failed" if action == "retry_failed" else "pending"
        summary = collection_queue_summary(status)
        candidate_ids = [item["candidateId"] for item in summary["items"] if item["source"] == "candidate"]
        run_ids = [item["id"] for item in summary["items"] if item["source"] == "automation_run"]
    created, updated, blocked = [], [], []
    if action == "start":
        if candidate_ids:
            result = collect_qualified_candidates(candidate_ids, payload.get("markets") or [], False)
            created.extend(result.get("items") or [])
            blocked.extend(result.get("blocked") or [])
        for run_id in run_ids:
            run = DB.get_run(run_id)
            if not run or run.get("kind") != "collection":
                blocked.append({"id": run_id, "error": "采集任务不存在"})
                continue
            if run.get("status") in ("queued", "waiting_browser", "preparing"):
                enqueue_automation_run(run["id"])
                updated.append(DB.get_run(run["id"]))
            elif run.get("status") in ("failed", "blocked"):
                try:
                    updated.append(retry_collection_run(run))
                except ValueError as exc:
                    blocked.append({"id": run_id, "error": str(exc)})
        return {"created": created, "updated": updated, "blocked": blocked, "summary": collection_queue_summary()}
    for run_id in run_ids:
        run = DB.get_run(run_id)
        if not run or run.get("kind") != "collection":
            blocked.append({"id": run_id, "error": "采集任务不存在"})
            continue
        try:
            if action == "retry_failed":
                if run.get("status") not in ("failed", "blocked"):
                    blocked.append({"id": run_id, "error": "只有失败采集任务可以重试"})
                    continue
                updated.append(retry_collection_run(run))
            elif action == "skip":
                updated.append(DB.update_run(run["id"], status="skipped", resolution="skipped"))
            elif action == "manual":
                updated.append(DB.update_run(run["id"], resolution="manual"))
                if run.get("candidate_id"):
                    DB.update_candidate(run["candidate_id"], {"status": "人工处理"})
        except ValueError as exc:
            blocked.append({"id": run_id, "error": str(exc)})
    if action in ("skip", "manual") and candidate_ids:
        for candidate_id in candidate_ids:
            candidate = DB.get_candidate(candidate_id)
            if not candidate:
                blocked.append({"id": candidate_id, "error": "候选商品不存在"})
                continue
            status = "已跳过" if action == "skip" else "人工处理"
            updated.append(DB.update_candidate(candidate_id, {"status": status}))
    return {"created": created, "updated": updated, "blocked": blocked, "summary": collection_queue_summary()}


def retry_generation_job(job_id):
    job = DB.row("SELECT * FROM generation_jobs WHERE id=?", (job_id,))
    if not job:
        raise ImageGatewayError("生图任务不存在")
    if job["status"] != "failed":
        raise ImageGatewayError("只有失败的生图任务可以重试")
    DB.execute(
        "UPDATE generation_jobs SET status='queued', error='', last_error='', updated_at=? WHERE id=?",
        (int(time.time()), job["id"]),
    )
    enqueue_generation(job["id"])
    return DB.row("SELECT * FROM generation_jobs WHERE id=?", (job["id"],))


def product_ids_from_payload(payload):
    ids = payload.get("productIds") or payload.get("product_ids") or []
    return [str(item) for item in ids if str(item or "").strip()]


def asset_ids_from_payload(payload):
    ids = payload.get("assetIds") or payload.get("asset_ids") or []
    return [str(item) for item in ids if str(item or "").strip()]


def assets_for_bulk_payload(payload):
    asset_ids = asset_ids_from_payload(payload)
    product_ids = product_ids_from_payload(payload)
    clauses, params = [], []
    if asset_ids:
        clauses.append("id IN (%s)" % ",".join("?" for _ in asset_ids))
        params.extend(asset_ids)
    if product_ids:
        clauses.append("product_id IN (%s)" % ",".join("?" for _ in product_ids))
        params.extend(product_ids)
    if not clauses:
        raise ValueError("请先选择图片或商品")
    return DB.rows("SELECT * FROM assets WHERE " + " OR ".join(clauses), params)


def approve_asset(asset_id):
    asset = DB.row("SELECT * FROM assets WHERE id=?", (asset_id,))
    if not asset:
        raise ValueError("图片不存在")
    DB.execute("UPDATE assets SET approved=1, review_status='approved', rejection_reason='' WHERE id=?", (asset["id"],))
    return DB.row("SELECT * FROM assets WHERE id=?", (asset["id"],))


def reject_asset(asset_id, reason):
    reason = str(reason or "其他").strip() or "其他"
    asset = DB.row("SELECT * FROM assets WHERE id=?", (asset_id,))
    if not asset:
        raise ValueError("图片不存在")
    DB.execute("UPDATE assets SET approved=0, review_status='rejected', rejection_reason=? WHERE id=?", (reason, asset["id"]))
    return DB.row("SELECT * FROM assets WHERE id=?", (asset["id"],))


def bulk_approve_assets(payload):
    assets = assets_for_bulk_payload(payload)
    for asset in assets:
        DB.execute("UPDATE assets SET approved=1, review_status='approved', rejection_reason='' WHERE id=?", (asset["id"],))
    return {"updated": len(assets), "items": assets_for_bulk_payload(payload)}


def bulk_reject_assets(payload):
    reason = str(payload.get("reason") or "其他").strip() or "其他"
    assets = assets_for_bulk_payload(payload)
    for asset in assets:
        DB.execute("UPDATE assets SET approved=0, review_status='rejected', rejection_reason=? WHERE id=?", (reason, asset["id"]))
    return {"updated": len(assets), "items": assets_for_bulk_payload(payload)}


def create_generation_job(product, preset, extra_prompt="", kinds=None):
    if not product:
        raise ValueError("商品不存在")
    if not product.get("mainImage"):
        raise ValueError("商品没有可用主图")
    custom = kinds if preset == "custom" else None
    prompts = build_prompts(product.get("category"), preset, custom, str(extra_prompt or ""))
    job_id = uuid.uuid4().hex
    now = int(time.time())
    DB.execute(
        "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (job_id, product["id"], preset, "queued", len(prompts), json.dumps({"prompts": prompts}, ensure_ascii=False), now, now),
    )
    enqueue_generation(job_id)
    return DB.row("SELECT * FROM generation_jobs WHERE id=?", (job_id,))


def bulk_generate_images(payload):
    product_ids = product_ids_from_payload(payload)
    if not product_ids:
        raise ValueError("请先选择商品")
    preset = str(payload.get("preset") or "standard")
    kinds = payload.get("kinds") if preset == "custom" else None
    jobs, blocked = [], []
    for product_id in product_ids:
        product = DB.get_product(product_id)
        try:
            jobs.append(create_generation_job(product, preset, payload.get("extraPrompt") or "", kinds))
        except Exception as exc:
            blocked.append({"productId": product_id, "title": (product or {}).get("title") or product_id, "error": str(exc)})
    return {"items": jobs, "blocked": blocked}


def retry_failed_generation_jobs(payload):
    product_ids = set(product_ids_from_payload(payload))
    jobs = DB.rows("SELECT * FROM generation_jobs WHERE status='failed' ORDER BY updated_at DESC")
    if product_ids:
        jobs = [job for job in jobs if job["product_id"] in product_ids]
    if not jobs:
        raise ValueError("没有可重试的失败生图任务")
    refreshed = []
    for job in jobs:
        refreshed.append(retry_generation_job(job["id"]))
    return {"updated": len(refreshed), "items": refreshed}


def infer_candidate_category(title, current=""):
    current = str(current or "").strip()
    if current:
        return current
    text = str(title or "")
    if "套装" in text:
        return "运动套装"
    if "包" in text:
        return "运动包"
    if "鞋" in text:
        return "运动鞋"
    return ""


def usable_source_title(title):
    title = str(title or "").strip()
    if any(marker in title for marker in ("请按照说明进行验证", "亲，请", "验证码", "安全验证")):
        return ""
    return title


def refresh_candidate_from_source(candidate_id):
    candidate = DB.get_candidate(candidate_id)
    if not candidate:
        return None
    if candidate_is_duplicate_skipped(candidate):
        raise ValueError("重复候选已跳过，不进入来源补全")
    scraped = scrape_product(str(candidate.get("source_url") or ""))
    images = scraped.get("images") or candidate.get("images") or []
    title = usable_source_title(scraped.get("title")) or str(candidate.get("title") or "").strip()
    updates = {
        "source_product_id": candidate.get("source_product_id") or source_product_id(candidate.get("source_url") or ""),
        "title": title,
        "category": infer_candidate_category(title, scraped.get("category") or candidate.get("category") or ""),
        "source_price": scraped.get("sourcePrice") or candidate.get("source_price") or 0,
        "weight_g": scraped.get("weightG") or candidate.get("weight_g") or 0,
        "image_count": len(images) or candidate.get("image_count") or 0,
        "images": images,
        "status": "待评估",
    }
    DB.update_candidate(candidate_id, updates)
    refreshed = DB.get_candidate(candidate_id)
    evaluations = evaluate_candidate(refreshed, {}, float(DB.setting("evaluation.min_margin", 20)))
    DB.save_evaluations(candidate_id, evaluations)
    status = evaluation_status(evaluations, float(DB.setting("evaluation.threshold", 70)), float(DB.setting("evaluation.min_confidence", 70)))
    DB.update_candidate(candidate_id, {"status": status})
    return candidate_summary(DB.get_candidate(candidate_id))


def refresh_candidates_from_sources(candidate_ids):
    ids = candidate_ids or [item["id"] for item in DB.list_candidates()]
    items, errors = [], []
    for candidate_id in ids:
        candidate = DB.get_candidate(candidate_id)
        if not candidate:
            errors.append({"id": candidate_id, "error": "候选商品不存在"})
            continue
        try:
            refreshed = refresh_candidate_from_source(candidate_id)
            if refreshed:
                items.append(candidate_summary(DB.get_candidate(candidate_id)))
        except Exception as exc:
            errors.append({
                "id": candidate_id,
                "title": candidate.get("title") or candidate.get("source_product_id") or candidate_id,
                "error": str(exc),
            })
    return {"items": [item for item in items if item], "errors": errors}


def evaluation_inputs_from_saved(candidate):
    markets = {}
    for evaluation in (candidate or {}).get("evaluations") or []:
        metrics = evaluation.get("metrics") or {}
        if not metrics:
            continue
        market = evaluation.get("market")
        markets[market] = {
            "trend": metrics.get("trend", 0),
            "salesSignal": metrics.get("sales_signal", 0),
            "competition": metrics.get("competition", 0),
            "targetPriceCny": metrics.get("target_price_cny", 0),
            "platformFeePct": metrics.get("platform_fee_pct", 12),
            "shippingCny": metrics.get("shipping_cny", 0),
            "dataComplete": metrics.get("market_data_complete", False),
        }
    return {"markets": markets} if markets else {}


def evaluate_candidates(candidate_ids):
    ids = candidate_ids or [item["id"] for item in DB.list_candidates()]
    results, blocked = [], []
    for candidate_id in ids:
        candidate = DB.get_candidate(candidate_id)
        if not candidate:
            continue
        summary = candidate_summary(candidate)
        if summary.get("duplicateSkipped"):
            blocked.append({
                "id": candidate_id,
                "title": summary.get("title") or summary.get("source_product_id") or candidate_id,
                "dedupeStatus": summary.get("dedupeStatus"),
                "dedupeReason": summary.get("dedupeReason"),
                "error": "重复候选已跳过，不进入评分",
            })
            continue
        if not summary["isReadyToScore"]:
            blocked.append({
                "id": candidate_id,
                "title": summary.get("title") or summary.get("source_product_id") or candidate_id,
                "missingFields": summary.get("dataCompleteness", {}).get("requiredMissingFields") or summary.get("missingFields") or [],
                "missingHints": summary.get("dataCompleteness", {}).get("requiredMissingHints") or summary.get("missingHints") or [],
                "error": "基础数据不完整，不能进入评分",
            })
            continue
        DB.update_candidate(candidate_id, {"status": "评估中"})
        evaluations = evaluate_candidate(candidate, evaluation_inputs_from_saved(candidate), float(DB.setting("evaluation.min_margin", 20)))
        DB.save_evaluations(candidate_id, evaluations)
        status = evaluation_status(
            evaluations,
            float(DB.setting("evaluation.threshold", 70)),
            float(DB.setting("evaluation.min_confidence", 70)),
        )
        DB.update_candidate(candidate_id, {"status": status})
        results.append(candidate_summary(DB.get_candidate(candidate_id)))
    return results, blocked


def source_image_bytes(url):
    if url.startswith("/images/"):
        path = (DATA_DIR / url.lstrip("/")).resolve()
        try:
            path.relative_to((DATA_DIR / "images").resolve())
        except ValueError:
            raise ImageGatewayError("本地主图路径无效")
        if not path.is_file():
            raise ImageGatewayError("本地主图不存在")
        data = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        return data, path.name
    if url.startswith("/assets/"):
        path = ASSET_DIR / Path(url).name
        if not path.is_file():
            raise ImageGatewayError("本地主图不存在")
        return path.read_bytes(), path.name
    try:
        data, content_type = fetch_image(url)
    except CollectError as exc:
        raise ImageGatewayError(str(exc))
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    return data, "reference" + extension


def run_generation(job_id):
    with GENERATION_SLOTS:
        job = DB.row("SELECT * FROM generation_jobs WHERE id=?", (job_id,))
        if not job:
            with GENERATION_LOCK:
                ACTIVE_GENERATIONS.discard(job_id)
            return
        product = DB.get_product(job["product_id"])
        prompts = (job.get("context") or {}).get("prompts") or []
        settings = DB.settings()
        now = int(time.time())
        failed_api = "%s%s" % (str(settings.get("image.base_url") or ""), str(settings.get("image.path") or ""))
        model = str(settings.get("image.model") or "")
        first_prompt = prompts[int(job.get("completed_count") or 0)] if prompts and int(job.get("completed_count") or 0) < len(prompts) else ""
        DB.execute(
            """UPDATE generation_jobs SET status='running',error='',last_error='',attempts=attempts+1,
            failed_api=?,model=?,last_prompt=?,last_run_at=?,updated_at=? WHERE id=?""",
            (failed_api, model, first_prompt, now, now, job_id),
        )
        completed = int(job.get("completed_count") or 0)
        try:
            if not product:
                raise ImageGatewayError("商品不存在")
            if not prompts:
                raise ImageGatewayError("生图任务缺少持久化提示词")
            source, source_name = source_image_bytes(product.get("mainImage") or "")
            retries = max(0, int(settings.get("image.retries") or 0))
            for index, prompt in enumerate(prompts[completed:], start=completed):
                DB.execute("UPDATE generation_jobs SET last_prompt=?, updated_at=? WHERE id=?", (prompt, int(time.time()), job_id))
                last_error = None
                for _ in range(retries + 1):
                    try:
                        images = generate(settings, prompt, source, source_name)
                        kind, value = images[0]
                        if kind == "url":
                            raw, content_type = fetch_image(value)
                        else:
                            raw, content_type = value, "image/png"
                        break
                    except Exception as exc:
                        last_error = exc
                else:
                    raise last_error
                extension = mimetypes.guess_extension(content_type) or ".png"
                extension = ".jpg" if extension in (".jpe", ".jpeg") else extension
                filename = "%s-%s%s" % (job_id, index + 1, extension)
                (ASSET_DIR / filename).write_bytes(raw)
                asset_id = uuid.uuid4().hex
                DB.execute(
                    "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (asset_id, product["id"], "/assets/" + filename, "generated", 0, "pending", "", prompt, int(time.time())),
                )
                completed += 1
                DB.execute("UPDATE generation_jobs SET completed_count=?, updated_at=? WHERE id=?", (completed, int(time.time()), job_id))
            DB.execute("UPDATE generation_jobs SET status='awaiting_approval',error='',updated_at=? WHERE id=?", (int(time.time()), job_id))
        except Exception as exc:
            DB.execute(
                "UPDATE generation_jobs SET status='failed', error=?, last_error=?, failed_api=?, model=?, updated_at=? WHERE id=?",
                (str(exc), str(exc), failed_api, model, int(time.time()), job_id),
            )
        finally:
            with GENERATION_LOCK:
                ACTIVE_GENERATIONS.discard(job_id)


def enqueue_generation(job_id):
    with GENERATION_LOCK:
        if job_id in ACTIVE_GENERATIONS:
            return False
        ACTIVE_GENERATIONS.add(job_id)
    threading.Thread(target=run_generation, args=(job_id,), daemon=True, name="image-job-" + job_id[:8]).start()
    return True


def ensure_product_from_candidate(candidate_id):
    candidate = DB.get_candidate(candidate_id)
    if not candidate:
        return None
    existing = DB.row("SELECT id FROM products WHERE candidate_id=? OR (source_product_id!='' AND source_product_id=?) LIMIT 1", (candidate_id, candidate.get("source_product_id") or ""))
    if existing:
        return DB.get_product(existing["id"])
    if not candidate_clean_title(candidate):
        clean_candidate_title(candidate_id)
        candidate = DB.get_candidate(candidate_id)
    images = candidate.get("images") or []
    local_images = candidate.get("local_images") or []
    main_image = images[0] if images else ""
    if candidate_image_ready(candidate) and local_images:
        first_local = Path(local_images[0])
        if first_local.is_file():
            main_image = "/images/%s/%s" % (candidate_id, first_local.name)
    product_title = candidate_display_title(candidate) or "1688商品 %s" % (candidate.get("source_product_id") or "")
    product = DB.save_product({
        "candidateId": candidate_id,
        "sourceProductId": candidate.get("source_product_id") or "",
        "sourceUrl": candidate.get("source_url") or "",
        "title": product_title,
        "category": candidate.get("category") or "",
        "sourcePrice": candidate.get("source_price") or 0,
        "costPrice": candidate.get("source_price") or 0,
        "weightG": candidate.get("weight_g") or 0,
        "images": images,
        "mainImage": main_image,
        "status": "待图片审核",
    })
    if hasattr(DB, "save_title_cleaning_record"):
        DB.save_title_cleaning_record({
            "candidate_id": candidate_id,
            "product_id": product["id"],
            "original_title": candidate.get("title") or "",
            "clean_title": product_title,
            "removed_terms": candidate.get("title_clean_removed_terms") or [],
            "risk_terms": candidate.get("title_clean_risk_terms") or [],
            "cleaned_at": candidate.get("title_cleaned_at") or int(time.time()),
        })
    create_market_versions(product["id"])
    if candidate_image_ready(candidate):
        ensure_candidate_ready_assets(product, candidate)
    return product


def register_collection_box_record(candidate, run=None, product=None):
    if not candidate:
        return None
    collected_at = int(time.time())
    clean_title = (product or {}).get("title") or candidate_display_title(candidate) or candidate.get("title") or ""
    return DB.save_collection_box_record({
        "candidate_id": candidate.get("id") or "",
        "offer_id": candidate.get("source_product_id") or "",
        "source_url": candidate.get("source_url") or "",
        "clean_title": clean_title,
        "image_status": candidate_image_status(candidate),
        "collected_at": collected_at,
        "miaoshou_status": (product or {}).get("status") or candidate.get("status") or "",
        "run_id": (run or {}).get("id") or "",
    })


def ensure_candidate_ready_assets(product, candidate):
    if not product or not candidate:
        return []
    existing = DB.rows("SELECT * FROM assets WHERE product_id=? AND kind='source' AND approved=1 AND review_status='approved'", (product["id"],))
    if existing:
        return existing
    created = []
    for index, local_path in enumerate(candidate.get("local_images") or []):
        local_path = Path(local_path)
        if not local_path.is_file():
            continue
        asset_id = uuid.uuid4().hex
        url = "/images/%s/%s" % (candidate["id"], local_path.name)
        DB.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (asset_id, product["id"], url, "source", 1, "approved", "", "图片自动判断原图可用 #%d" % (index + 1), int(time.time())),
        )
        created.append(DB.row("SELECT * FROM assets WHERE id=?", (asset_id,)))
    return created


def ensure_approved_asset_for_product(product):
    existing = DB.row("SELECT * FROM assets WHERE product_id=? AND approved=1 AND review_status!='rejected' LIMIT 1", (product["id"],))
    if existing:
        return existing
    image = product.get("mainImage") or (product.get("images") or [""])[0]
    if not image:
        return None
    if image.startswith("/assets/") or image.startswith("/images/"):
        url = image
    else:
        raw, content_type = fetch_image(image)
        extension = mimetypes.guess_extension(content_type) or ".jpg"
        extension = ".jpg" if extension in (".jpe", ".jpeg") else extension
        filename = "%s-approved%s" % (product["id"], extension)
        (ASSET_DIR / filename).write_bytes(raw)
        url = "/assets/" + filename
    asset_id = uuid.uuid4().hex
    DB.execute(
        "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (asset_id, product["id"], url, "source", 1, "approved", "", "自检自动登记的候选主图", int(time.time())),
    )
    return DB.row("SELECT * FROM assets WHERE id=?", (asset_id,))


def selfcheck_repair(max_refresh=5):
    before = system_selfcheck()
    actions, errors = [], []
    candidates = [candidate_summary(item) for item in DB.list_candidates()]
    needs_refresh = [
        item["id"] for item in candidates
        if not item.get("category") or not item.get("source_price") or not item.get("weight_g")
        or not (item.get("image_count") or item.get("images"))
    ]
    if needs_refresh:
        limited = needs_refresh[:max(0, int(max_refresh))]
        result = refresh_candidates_from_sources(limited)
        actions.append("来源补全 %d 个候选，失败 %d 个" % (len(result["items"]), len(result["errors"])))
        if len(needs_refresh) > len(limited):
            actions.append("仍有 %d 个候选待批量补全" % (len(needs_refresh) - len(limited)))
        errors.extend(result["errors"])

    evaluated, blocked_evaluations = evaluate_candidates([item["id"] for item in DB.list_candidates()])
    if evaluated:
        actions.append("重新评估 %d 个候选" % len(evaluated))
    for item in blocked_evaluations:
        errors.append({"id": item["id"], "title": item.get("title", ""), "error": item["error"]})

    products_before = len(DB.list_products())
    for candidate in DB.list_candidates():
        summary = candidate_summary(candidate)
        if summary.get("qualifiedMarkets") and not summary.get("duplicateSkipped"):
            ensure_product_from_candidate(summary["id"])
    products_after = DB.list_products()
    created = len(products_after) - products_before
    if created:
        actions.append("从达标候选创建 %d 个正式商品" % created)

    approved_count = 0
    for product in products_after:
        if DB.row("SELECT id FROM assets WHERE product_id=? AND approved=1 AND review_status!='rejected' LIMIT 1", (product["id"],)):
            continue
        try:
            if ensure_approved_asset_for_product(product):
                approved_count += 1
        except (CollectError, ImageGatewayError, OSError, ValueError) as exc:
            errors.append({"id": product["id"], "title": product.get("title", ""), "error": str(exc)})
    if approved_count:
        actions.append("登记 %d 个商品主图为已审核素材" % approved_count)

    after = system_selfcheck()
    unresolved = [item for item in after["checks"] if item["status"] != "pass"]
    return {
        "before": before,
        "after": after,
        "actions": actions,
        "errors": errors,
        "unresolved": unresolved,
        "nextSteps": classify_selfcheck_steps(unresolved),
    }


def execute_automation_run(run_id, confirm=False):
    run = DB.get_run(run_id)
    if not run:
        with RUN_LOCK:
            ACTIVE_RUNS.discard(run_id)
        return
    phase = (run.get("context") or {}).get("phase", "prepare")
    confirm = confirm or phase == "confirm"
    try:
        DB.update_run(run_id, status="running", error="")
        if run.get("kind") in ("collection", "publish", "keyword_search"):
            platform = BROWSER.platform_status()
            if platform.get("waiting_for_manual") and not AUTOMATION.is_dry_run(run):
                block_run_for_manual(run, platform)
                return
        result = AUTOMATION.confirm_publish(run_id) if confirm else AUTOMATION.run(run_id)
        if result and result.get("kind") == "collection" and result.get("status") == "completed":
            product = ensure_product_from_candidate(result.get("candidate_id"))
            candidate = DB.get_candidate(result.get("candidate_id")) if result.get("candidate_id") else None
            register_collection_box_record(candidate, run=DB.get_run(run_id), product=product)
        elif result and result.get("kind") == "collection" and result.get("status") == "ready_for_live":
            DB.update_candidate(result.get("candidate_id"), {"status": "等待真实采集"})
        elif result and result.get("kind") == "collection" and result.get("status") in ("blocked", "failed"):
            DB.update_candidate(result.get("candidate_id"), {"status": "人工处理"})
        if result and result.get("kind") == "publish" and result.get("batch_id"):
            if confirm and result.get("status") == "completed":
                dry_run = AUTOMATION.is_dry_run(result)
                batch_status = "completed_dry_run" if dry_run else "completed"
                key_status = "dry_run" if dry_run else "published"
                DB.execute("UPDATE batches SET status=?,updated_at=? WHERE id=?", (batch_status, int(time.time()), result["batch_id"]))
                DB.execute(
                    "UPDATE publish_keys SET status=?,result=?,failure_reason='',published_at=? WHERE batch_id=?",
                    (key_status, "演练通过" if dry_run else "发布成功", int(time.time()), result["batch_id"]),
                )
            elif result.get("status") in ("blocked", "failed"):
                DB.execute("UPDATE batches SET status=?,updated_at=? WHERE id=?", (result["status"], int(time.time()), result["batch_id"]))
            elif not confirm and result.get("status") == "waiting_confirmation":
                DB.execute("UPDATE batches SET status='preparing',updated_at=? WHERE id=?", (int(time.time()), result["batch_id"]))
    except Exception as exc:
        DB.update_run(run_id, status="failed", error=str(exc))
        if run.get("batch_id"):
            DB.execute("UPDATE batches SET status='failed',updated_at=? WHERE id=?", (int(time.time()), run["batch_id"]))
    finally:
        with RUN_LOCK:
            ACTIVE_RUNS.discard(run_id)


def enqueue_automation_run(run_id, confirm=False):
    with RUN_LOCK:
        if run_id in ACTIVE_RUNS:
            return False
        ACTIVE_RUNS.add(run_id)
    threading.Thread(
        target=execute_automation_run, args=(run_id, confirm), daemon=True,
        name="automation-run-" + run_id[:8],
    ).start()
    return True


def sourcing_current_status():
    run = SOURCING.current()
    limits = SOURCING.normalize_limits()
    return {
        "run": run,
        "active": bool(run and run.get("run_id") in ACTIVE_SOURCING_RUNS),
        "config": limits,
        "status": run.get("status") if run else "idle",
    }


def execute_sourcing_run(run_id):
    try:
        SOURCING.run_once(run_id)
    finally:
        with SOURCING_LOCK:
            ACTIVE_SOURCING_RUNS.discard(run_id)


def enqueue_sourcing_run(run_id):
    with SOURCING_LOCK:
        if run_id in ACTIVE_SOURCING_RUNS:
            return False
        ACTIVE_SOURCING_RUNS.add(run_id)
    threading.Thread(
        target=execute_sourcing_run,
        args=(run_id,),
        daemon=True,
        name="sourcing-run-" + run_id[:8],
    ).start()
    return True


def recover_background_jobs():
    for job in DB.rows("SELECT id FROM generation_jobs WHERE status='queued'"):
        enqueue_generation(job["id"])
    for run in DB.rows("SELECT id FROM automation_runs WHERE status='queued'"):
        enqueue_automation_run(run["id"])
    for run in DB.rows(
        "SELECT run_id FROM sourcing_runs WHERE status IN (%s)" % ",".join("?" for _ in SOURCING_ACTIVE_STATUSES),
        tuple(SOURCING_ACTIVE_STATUSES),
    ):
        DB.update_sourcing_run(run["run_id"], status="waiting_for_manual", error="服务重启后等待继续")


def create_market_versions(product_id):
    product = DB.get_product(product_id)
    candidate = DB.get_candidate(product.get("candidateId")) if product and product.get("candidateId") else None
    evaluations = {item["market"]: item for item in (candidate or {}).get("evaluations", [])}
    for market, info in MARKET_INFO.items():
        evaluation = evaluations.get(market) or {}
        reasons = evaluation.get("hard_blocks") or []
        cost = float(product.get("costPrice") or product.get("sourcePrice") or 0)
        shipping = float(DB.setting("market.%s.shipping_cny" % market, 20))
        fee = float(DB.setting("market.platform_fee_pct", 12)) / 100
        margin = float(DB.setting("market.target_margin_pct", 25)) / 100
        exchange = float(DB.setting("market.%s.exchange" % market, 1))
        denominator = max(0.1, 1 - fee - margin)
        local_price = round(((cost + shipping) / denominator) * exchange, 2) if cost else 0
        DB.execute(
            """INSERT INTO market_versions(id,product_id,market,language,title,description,currency,sale_price,blocked,block_reasons)
            VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(product_id,market) DO UPDATE SET
            language=excluded.language,currency=excluded.currency,
            sale_price=CASE WHEN market_versions.sale_price=0 THEN excluded.sale_price ELSE market_versions.sale_price END,
            blocked=excluded.blocked,block_reasons=excluded.block_reasons""",
            (uuid.uuid4().hex, product_id, market, info["language"], product.get("title", ""), product.get("notes", ""),
             info["currency"], local_price, int(bool(reasons)), json.dumps(reasons, ensure_ascii=False)),
        )


def validate_batch(batch):
    preview = batch_preflight(batch)
    return [item["message"] for item in preview["risks"] if item["severity"] == "error"]


def publish_key_for(product, shop):
    return "%s|%s|%s|%s" % (
        product.get("sourceProductId") or product.get("sourceUrl"),
        product.get("sku") or product["id"],
        shop["account_name"],
        shop["shop_name"],
    )


def batch_risk(category, severity, message, product=None, shop=None, market="", detail=""):
    return {
        "category": category,
        "severity": severity,
        "message": message,
        "productId": (product or {}).get("id", ""),
        "productTitle": (product or {}).get("title", ""),
        "shopId": (shop or {}).get("id", ""),
        "shopName": (shop or {}).get("shop_name", ""),
        "market": market or (shop or {}).get("market", ""),
        "detail": detail,
    }


def batch_margin_pct(product, version, market):
    sale_price = float(version.get("sale_price") or 0)
    if sale_price <= 0:
        return None
    exchange = float(DB.setting("market.%s.exchange" % market, 1) or 1)
    fee = float(DB.setting("market.platform_fee_pct", 12) or 0) / 100
    shipping = float(DB.setting("market.%s.shipping_cny" % market, 20) or 0)
    cost = float(product.get("costPrice") or product.get("sourcePrice") or 0)
    sale_cny = sale_price / max(exchange, 0.0001)
    if sale_cny <= 0:
        return None
    return round(((sale_cny * (1 - fee) - cost - shipping) / sale_cny) * 100, 1)


def candidate_confidence_for_market(product, market):
    candidate_id = (product or {}).get("candidateId")
    if not candidate_id:
        return None
    candidate = DB.get_candidate(candidate_id)
    if not candidate:
        return None
    evaluation = next((item for item in (candidate.get("evaluations") or []) if item.get("market") == market), None)
    if not evaluation:
        return None
    return float(evaluation.get("confidence") or 0)


def automation_environment_risks():
    try:
        checks = AUTOMATION.preflight()
    except Exception as exc:
        return [batch_risk("environment", "warning", "妙手环境预检失败", detail=str(exc))]
    risks = []
    if not checks.get("chromeInstalled"):
        risks.append(batch_risk("environment", "warning", "未检测到可用 Chrome", detail=checks.get("chromePath", "")))
    if not checks.get("cdpConnected"):
        risks.append(batch_risk("environment", "warning", "专用 Chrome 尚未连接", detail="发布前需要启动并保持登录"))
    if not checks.get("pluginVerified"):
        risks.append(batch_risk("environment", "warning", "妙手插件未确认可用", detail="请在系统设置完成插件自检"))
    if not checks.get("miaoshouLoginVerified"):
        risks.append(batch_risk("environment", "warning", "妙手登录状态未确认", detail="真实发布前需要确认已登录妙手"))
    if checks.get("requiresCalibration"):
        risks.append(batch_risk("environment", "warning", "发布动作配方未校准", detail="系统设置中补充发布动作配方后更稳妥"))
    return risks


def batch_preflight(batch):
    product_ids = list(dict.fromkeys(batch.get("product_ids") or batch.get("productIds") or []))
    shop_ids = list(dict.fromkeys(batch.get("shop_ids") or batch.get("shopIds") or []))
    current_batch_id = batch.get("id") or ""
    products = {item["id"]: item for item in DB.list_products()}
    shops = {item["id"]: item for item in DB.rows("SELECT * FROM shops")}
    approved = approved_asset_product_ids()
    approved_asset_counts = {
        row["product_id"]: row["count"]
        for row in DB.rows("SELECT product_id, COUNT(*) AS count FROM assets WHERE approved=1 AND review_status!='rejected' GROUP BY product_id")
    }
    publish_keys = {item["idempotency_key"]: item for item in DB.rows("SELECT * FROM publish_keys")}
    risks = []
    tasks = 0
    version_keys = set()
    min_margin = float(DB.setting("evaluation.min_margin", 20) or 20)
    min_confidence = float(DB.setting("evaluation.min_confidence", 70) or 70)

    if not product_ids:
        risks.append(batch_risk("selection", "error", "批次必须选择商品"))
    if not shop_ids:
        risks.append(batch_risk("selection", "error", "批次必须选择店铺"))
    if len(product_ids) > 50:
        risks.append(batch_risk("selection", "error", "单批最多50款商品"))
    if len(shop_ids) > 20:
        risks.append(batch_risk("selection", "error", "单批最多20家店铺"))

    for product_id in product_ids:
        product = products.get(product_id)
        if not product:
            risks.append(batch_risk("missing_product", "error", "商品 %s 不存在" % product_id, detail=product_id))
            continue
        if product_id not in approved:
            risks.append(batch_risk("missing_image", "error", "%s 缺少审核通过的图片" % (product.get("title") or product_id), product=product))
        elif int(approved_asset_counts.get(product_id) or 0) < 3:
            risks.append(batch_risk("image_count", "warning", "%s 审核通过图片偏少" % (product.get("title") or product_id), product=product, detail="当前 %d 张，建议至少 3 张" % int(approved_asset_counts.get(product_id) or 0)))
        versions = {item["market"]: item for item in DB.market_versions(product_id)}
        for shop_id in shop_ids:
            shop = shops.get(shop_id)
            if not shop:
                risks.append(batch_risk("missing_shop", "error", "店铺 %s 不存在" % shop_id, product=product, detail=shop_id))
                continue
            if not shop.get("enabled"):
                risks.append(batch_risk("shop_disabled", "error", "%s 店铺不可用" % shop["shop_name"], product=product, shop=shop))
            tasks += 1
            version = versions.get(shop["market"])
            prefix = "%s → %s" % (product.get("title") or product_id, shop["shop_name"])
            if not version:
                risks.append(batch_risk("missing_version", "error", prefix + " 缺少国家版本", product=product, shop=shop))
                continue
            version_keys.add("%s:%s" % (product_id, shop["market"]))
            if version["blocked"]:
                reasons = "；".join(version.get("block_reasons") or [])
                risks.append(batch_risk("blocked_market", "error", prefix + " 被风险规则拦截", product=product, shop=shop, detail=reasons))
            if not version["title"].strip():
                risks.append(batch_risk("missing_title", "error", prefix + " 缺少本地标题", product=product, shop=shop))
            elif len(version["title"].strip()) < 8:
                risks.append(batch_risk("short_title", "warning", prefix + " 标题较短", product=product, shop=shop, detail=version["title"].strip()))
            if float(version["sale_price"] or 0) <= 0:
                risks.append(batch_risk("price", "error", prefix + " 缺少售价", product=product, shop=shop))
            else:
                margin_pct = batch_margin_pct(product, version, shop["market"])
                if margin_pct is not None and margin_pct < min_margin:
                    risks.append(batch_risk("margin", "warning", prefix + " 毛利率偏低", product=product, shop=shop, detail="预计 %.1f%%，门槛 %.1f%%" % (margin_pct, min_margin)))
            confidence = candidate_confidence_for_market(product, shop["market"])
            if confidence is not None and confidence < min_confidence:
                risks.append(batch_risk("confidence", "warning", prefix + " 商品数据置信度不足", product=product, shop=shop, detail="置信度 %.1f，门槛 %.1f" % (confidence, min_confidence)))
            warehouse = version["warehouse"].strip() or shop["warehouse"].strip()
            inventory = int(version["inventory"] or shop["default_inventory"] or 0)
            if not warehouse:
                risks.append(batch_risk("warehouse", "error", prefix + " 缺少仓库", product=product, shop=shop))
            if inventory <= 0:
                risks.append(batch_risk("inventory", "error", prefix + " 库存必须大于0", product=product, shop=shop))
            key = publish_key_for(product, shop)
            existing = publish_keys.get(key)
            if existing and existing.get("batch_id") != current_batch_id and existing.get("status") in ("reserved", "published"):
                risks.append(batch_risk(
                    "duplicate",
                    "error",
                    prefix + " 存在重复铺货风险",
                    product=product,
                    shop=shop,
                    detail="已在批次 %s 中%s" % (existing.get("batch_id"), "发布" if existing.get("status") == "published" else "预留"),
                ))

    risks.extend(automation_environment_risks())
    severity_order = {"error": 0, "warning": 1}
    risks.sort(key=lambda item: (severity_order.get(item.get("severity"), 2), item.get("category", ""), item.get("message", "")))
    categories = [
        "missing_image", "blocked_market", "duplicate", "price", "inventory", "warehouse",
        "missing_version", "missing_product", "missing_shop", "missing_title", "selection",
        "shop_disabled", "environment", "margin", "short_title", "image_count", "confidence",
    ]
    counts = {category: sum(1 for item in risks if item["category"] == category) for category in categories}
    errors = sum(1 for item in risks if item["severity"] == "error")
    warnings = sum(1 for item in risks if item["severity"] == "warning")
    status = "blocked" if errors else "warning" if warnings else "executable"
    return {
        "ready": errors == 0,
        "status": status,
        "statusLabel": {"blocked": "阻塞", "warning": "警告", "executable": "可执行"}[status],
        "productCount": len(product_ids),
        "shopCount": len(shop_ids),
        "versionCount": len(version_keys),
        "taskCount": tasks,
        "dryRun": bool(batch.get("dry_run", batch.get("dryRun", True))),
        "counts": counts,
        "errors": errors,
        "blockingCount": errors,
        "warnings": warnings,
        "warningCount": warnings,
        "duplicateRiskCount": counts.get("duplicate", 0),
        "risks": risks,
    }


def batch_summary_from_preview(preview):
    return {
        "products": preview["productCount"],
        "shops": preview["shopCount"],
        "versions": preview.get("versionCount", 0),
        "publishTasks": preview["taskCount"],
        "ready": preview["ready"],
        "status": preview.get("status", "executable" if preview["ready"] else "blocked"),
        "errors": preview["errors"],
        "warnings": preview["warnings"],
        "blockingCount": preview.get("blockingCount", preview["errors"]),
        "warningCount": preview.get("warningCount", preview["warnings"]),
        "duplicateRiskCount": preview.get("duplicateRiskCount", preview.get("counts", {}).get("duplicate", 0)),
        "riskCounts": preview["counts"],
    }


def create_batch_from_payload(payload):
    product_ids = list(dict.fromkeys(payload.get("productIds") or []))
    shop_ids = list(dict.fromkeys(payload.get("shopIds") or []))
    preview = batch_preflight({
        "productIds": product_ids,
        "shopIds": shop_ids,
        "dryRun": payload.get("dryRun", True),
    })
    if not preview["ready"]:
        errors = [item["message"] for item in preview["risks"] if item["severity"] == "error"]
        return None, preview, "批次预检失败：" + "；".join(errors[:10])
    batch_id = uuid.uuid4().hex
    now = int(time.time())
    summary = batch_summary_from_preview(preview)
    DB.execute(
        "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            batch_id, payload.get("name") or "铺货批次", "draft", int(payload.get("dryRun", True)),
            json.dumps(product_ids), json.dumps(shop_ids), json.dumps(summary, ensure_ascii=False), now, now,
        ),
    )
    return DB.row("SELECT * FROM batches WHERE id=?", (batch_id,)), preview, ""


def batch_confirmation_phrase(batch):
    summary = batch_summary_from_preview(batch_preflight(batch))
    mode = "DRY" if batch.get("dry_run") else "LIVE"
    return "CONFIRM %sx%s %s" % (summary.get("products", 0), summary.get("shops", 0), mode)


def batch_report(batch):
    preview = batch_preflight(batch)
    runs = DB.rows("SELECT * FROM automation_runs WHERE batch_id=? AND kind='publish' ORDER BY created_at DESC", (batch["id"],))
    failures = [run for run in runs if run.get("status") in ("failed", "blocked")]
    blocked_items = [item for item in preview["risks"] if item["severity"] == "error"]
    return {
        "batchId": batch["id"],
        "batchName": batch["name"],
        "dryRun": bool(batch.get("dry_run")),
        "products": preview["productCount"],
        "shops": preview["shopCount"],
        "versions": preview.get("versionCount", 0),
        "tasks": preview["taskCount"],
        "successSteps": sum(1 for run in runs if run.get("status") == "completed"),
        "failedSteps": sum(1 for run in runs if run.get("status") in ("failed", "blocked")),
        "blockedItems": blocked_items,
        "failedTasks": [
            {
                "id": run["id"],
                "currentStep": run.get("current_step") or "",
                "error": run.get("error") or "",
                "diagnostics": run.get("diagnostics") or {},
            }
            for run in failures
        ],
        "suggestLivePublish": preview["ready"] and not blocked_items,
    }


def matching_dry_run_report(batch):
    product_ids = set(batch.get("product_ids") or [])
    shop_ids = set(batch.get("shop_ids") or [])
    for item in DB.rows("SELECT * FROM batches WHERE dry_run=1 ORDER BY updated_at DESC"):
        if set(item.get("product_ids") or []) != product_ids or set(item.get("shop_ids") or []) != shop_ids:
            continue
        report = batch_report(item)
        if item.get("status") == "completed_dry_run" and report.get("suggestLivePublish"):
            return report
    return None


def unhandled_batch_failures(batch):
    return DB.rows(
        "SELECT * FROM automation_runs WHERE batch_id=? AND kind='publish' AND status IN ('failed','blocked') ORDER BY updated_at DESC",
        (batch["id"],),
    )


def batch_live_publish_gate(batch, payload=None):
    payload = payload or {}
    if batch.get("dry_run"):
        return {"allowed": True, "dryRunReport": batch_report(batch), "skipDryRun": False, "blockedReasons": []}
    preview = batch_preflight(batch)
    blocked = []
    if workbench_config().get("no_publish", True):
        blocked.append("no_publish=true：禁止真实发布确认")
    if not preview["ready"]:
        blocked.extend(item["message"] for item in preview["risks"] if item["severity"] == "error")
    failures = unhandled_batch_failures(batch)
    if failures:
        blocked.append("存在未处理失败任务")
    dry_report = matching_dry_run_report(batch)
    skip_dry_run = bool(payload.get("skipDryRun"))
    if not dry_report and not skip_dry_run:
        blocked.append("真实发布前需要先完成同商品同店铺组合的演练，或明确勾选跳过演练")
    return {
        "allowed": not blocked,
        "dryRunReport": dry_report,
        "skipDryRun": skip_dry_run,
        "blockedReasons": blocked,
        "unhandledFailures": [run["id"] for run in failures],
    }


def batch_confirmation_summary(batch):
    preview = batch_preflight(batch)
    latest_run = DB.row(
        "SELECT * FROM automation_runs WHERE batch_id=? AND kind='publish' ORDER BY created_at DESC LIMIT 1",
        (batch["id"],),
    )
    live_gate = batch_live_publish_gate(batch) if not batch.get("dry_run") else {"allowed": True, "dryRunReport": batch_report(batch), "skipDryRun": False, "blockedReasons": []}
    return {
        "batch": batch,
        "run": latest_run,
        "preflight": preview,
        "phrase": batch_confirmation_phrase(batch),
        "mode": "演练模式" if batch.get("dry_run") else "真实发布",
        "liveGate": live_gate,
        "dryRunReport": live_gate.get("dryRunReport") or batch_report(batch),
        "canConfirm": bool(latest_run and latest_run.get("status") == "waiting_confirmation" and preview["ready"] and live_gate.get("allowed")),
        "summary": {
            "products": preview["productCount"],
            "shops": preview["shopCount"],
            "versions": preview.get("versionCount", 0),
            "publishTasks": preview["taskCount"],
            "missingImages": preview["counts"].get("missing_image", 0),
            "blockedMarkets": preview["counts"].get("blocked_market", 0),
            "duplicateRisks": preview["counts"].get("duplicate", 0),
            "priceIssues": preview["counts"].get("price", 0),
            "inventoryIssues": preview["counts"].get("inventory", 0),
            "warehouseIssues": preview["counts"].get("warehouse", 0),
            "unhandledFailures": len(live_gate.get("unhandledFailures") or []),
        },
    }


def require_batch_confirmation(batch, payload):
    phrase = str(payload.get("confirmation") or "").strip()
    expected = batch_confirmation_phrase(batch)
    if phrase != expected:
        raise ValueError("请输入确认短语：%s" % expected)
    return phrase


def confirm_batch(batch_id, payload):
    batch = DB.row("SELECT * FROM batches WHERE id=?", (batch_id,))
    if not batch:
        raise ValueError("批次不存在")
    run = DB.row("SELECT * FROM automation_runs WHERE batch_id=? AND kind='publish' ORDER BY created_at DESC LIMIT 1", (batch["id"],))
    preview = batch_preflight(batch)
    if not run or run["status"] != "waiting_confirmation":
        raise ValueError("批次尚未完成发布前准备，不能确认")
    if not preview["ready"]:
        errors = [item["message"] for item in preview["risks"] if item["severity"] == "error"]
        raise ValueError("批次预检失败：" + "；".join(errors[:10]))
    live_gate = batch_live_publish_gate(batch, payload)
    if not live_gate["allowed"]:
        raise ValueError("真实发布门禁失败：" + "；".join(live_gate["blockedReasons"][:10]))
    expected = batch_confirmation_phrase(batch)
    require_batch_confirmation(batch, payload)
    now = int(time.time())
    DB.execute("UPDATE batches SET status='confirmed',confirmed_at=?,updated_at=? WHERE id=?", (now, now, batch["id"]))
    context = {**(run.get("context") or {}), "phase": "confirm", "skipDryRun": live_gate["skipDryRun"]}
    DB.update_run(run["id"], status="queued", error="", context=context)
    enqueue_automation_run(run["id"], confirm=True)
    return {"batch": DB.row("SELECT * FROM batches WHERE id=?", (batch["id"],)), "run": DB.get_run(run["id"]), "phrase": expected}


def run_label(run):
    if run.get("kind") == "collection":
        return "妙手采集"
    if run.get("kind") == "publish":
        return "铺货发布"
    if run.get("kind") == "keyword_search":
        return "关键词找品"
    return run.get("kind") or "自动化任务"


def failure_task(source, item_id, task_type, reason, **extra):
    actions = extra.pop("actions", ["mark_handled", "manual"])
    return {
        "source": source,
        "id": item_id,
        "type": task_type,
        "label": task_type,
        "product": extra.pop("product", ""),
        "productId": extra.pop("productId", ""),
        "market": extra.pop("market", ""),
        "shop": extra.pop("shop", ""),
        "shopId": extra.pop("shopId", ""),
        "batch": extra.pop("batch", ""),
        "batchId": extra.pop("batchId", ""),
        "currentStep": extra.pop("currentStep", ""),
        "reason": reason or "未记录失败原因",
        "error": reason or "未记录失败原因",
        "screenshot": extra.pop("screenshot", ""),
        "currentUrl": extra.pop("currentUrl", ""),
        "attempts": extra.pop("attempts", 0),
        "lastFailedAt": extra.pop("lastFailedAt", None),
        "suggestedActions": extra.pop("suggestedActions", ["检查详情后处理"]),
        "actions": actions,
        "resolution": extra.pop("resolution", ""),
        **extra,
    }


def failure_action_for_run(run):
    if run.get("resolution") == "handled":
        return []
    if run.get("resolution") in ("skipped", "manual"):
        return ["mark_handled"]
    return ["retry", "skip", "mark_handled", "manual", "details", "copy"]


def publish_result_stats(publish_keys, shops):
    total = len([item for item in publish_keys if item.get("status") in ("published", "failed", "skipped", "blocked", "dry_run")])
    success = len([item for item in publish_keys if item.get("status") in ("published", "dry_run")])
    failed = len([item for item in publish_keys if item.get("status") in ("failed", "blocked")])
    skipped = len([item for item in publish_keys if item.get("status") == "skipped"])
    duplicate = len([item for item in publish_keys if item.get("status") == "duplicate"])
    def grouped_rate(key):
        groups = {}
        for item in publish_keys:
            label = item.get(key) or "未记录"
            if key == "shop_id":
                label = (shops.get(item.get("shop_id") or "") or {}).get("shop_name") or label
            bucket = groups.setdefault(label, {"total": 0, "success": 0, "failed": 0, "successRate": 0})
            if item.get("status") in ("published", "failed", "skipped", "blocked", "dry_run"):
                bucket["total"] += 1
            if item.get("status") in ("published", "dry_run"):
                bucket["success"] += 1
            if item.get("status") in ("failed", "blocked"):
                bucket["failed"] += 1
        for bucket in groups.values():
            bucket["successRate"] = round(bucket["success"] / bucket["total"] * 100, 1) if bucket["total"] else 0
        return [{"name": name, **value} for name, value in groups.items()]
    return {
        "totalTasks": total,
        "successTasks": success,
        "failedTasks": failed,
        "skippedTasks": skipped,
        "duplicateBlocked": duplicate,
        "successRate": round(success / total * 100, 1) if total else 0,
        "shopStats": grouped_rate("shop_id"),
        "marketStats": grouped_rate("market"),
    }


def publish_results_summary():
    runs = DB.list_runs()
    batches = {item["id"]: item for item in DB.rows("SELECT * FROM batches")}
    products = {item["id"]: item for item in DB.list_products()}
    shops = {item["id"]: item for item in DB.rows("SELECT * FROM shops")}
    publish_keys = DB.rows("SELECT * FROM publish_keys")
    publish_stats = publish_result_stats(publish_keys, shops)
    failed_statuses = {"failed", "blocked"}
    active_statuses = {"queued", "running", "preparing", "waiting_browser"}
    waiting_statuses = {"waiting_confirmation", "awaiting_claim", "ready_for_live", "waiting_for_manual"}
    overview = {
        "totalRuns": len(runs),
        "completedRuns": sum(1 for item in runs if item.get("status") == "completed"),
        "failedRuns": sum(1 for item in runs if item.get("status") in failed_statuses),
        "activeRuns": sum(1 for item in runs if item.get("status") in active_statuses),
        "waitingRuns": sum(1 for item in runs if item.get("status") in waiting_statuses),
        "publishedTasks": sum(1 for item in publish_keys if item.get("status") == "published"),
        "dryRunTasks": sum(1 for item in publish_keys if item.get("status") == "dry_run"),
        "reservedTasks": sum(1 for item in publish_keys if item.get("status") == "reserved"),
        **publish_stats,
    }
    failures = []
    waiting = []
    recent = []
    for run in runs:
        batch = batches.get(run.get("batch_id") or "")
        diagnostics = run.get("diagnostics") or {}
        item = {
            "id": run["id"],
            "kind": run.get("kind"),
            "label": run_label(run),
            "status": run.get("status"),
            "batchId": run.get("batch_id") or "",
            "batchName": (batch or {}).get("name", ""),
            "currentStep": run.get("current_step") or "",
            "error": diagnostics.get("error") or run.get("error") or "",
            "diagnostics": diagnostics,
            "screenshot": diagnostics.get("screenshot") or run.get("screenshot") or "",
            "suggestedActions": diagnostics.get("suggestedActions") or (["检查配置后重试"] if run.get("status") in failed_statuses else []),
            "createdAt": run.get("created_at"),
            "updatedAt": run.get("updated_at"),
            "attempts": run.get("attempts") or 0,
            "resolution": run.get("resolution") or "",
        }
        recent.append(item)
        if run.get("status") in failed_statuses:
            failures.append(failure_task(
                "automation_run",
                run["id"],
                run_label(run),
                item["error"],
                batch=item["batchName"],
                batchId=item["batchId"],
                currentStep=item["currentStep"],
                screenshot=item["screenshot"],
                currentUrl=diagnostics.get("currentUrl") or "",
                attempts=item["attempts"],
                lastFailedAt=item["updatedAt"],
                suggestedActions=item["suggestedActions"],
                actions=failure_action_for_run(run),
                resolution=item["resolution"],
            ))
        elif run.get("status") in waiting_statuses:
            waiting.append(item)
    for job in DB.rows("SELECT * FROM generation_jobs WHERE status='failed' ORDER BY updated_at DESC"):
        product = products.get(job.get("product_id") or "")
        failures.append(failure_task(
            "generation_job",
            job["id"],
            "生图失败",
            job.get("last_error") or job.get("error") or "生图任务失败",
            product=(product or {}).get("title", ""),
            productId=job.get("product_id") or "",
            currentStep="AI图片生成",
            attempts=job.get("attempts") or 0,
            lastFailedAt=job.get("updated_at"),
            suggestedActions=image_failure_guidance(job.get("error") or job.get("last_error")),
            actions=["retry", "mark_handled", "manual", "details", "copy"],
            model=job.get("model") or "",
            prompt=job.get("last_prompt") or "",
        ))
    for asset in DB.rows("SELECT * FROM assets WHERE review_status='rejected' ORDER BY created_at DESC"):
        product = products.get(asset.get("product_id") or "")
        failures.append(failure_task(
            "asset",
            asset["id"],
            "图片审核不通过",
            asset.get("rejection_reason") or "图片审核不通过",
            product=(product or {}).get("title", ""),
            productId=asset.get("product_id") or "",
            currentStep="图片审核",
            screenshot=asset.get("url") or "",
            lastFailedAt=asset.get("created_at"),
            suggestedActions=["按驳回原因重新生成或上传图片", "审核通过后再进入铺货批次"],
            actions=["mark_handled", "manual", "details", "copy"],
        ))
    failed_batch_ids = {item.get("batchId") for item in failures if item.get("batchId")}
    for batch in batches.values():
        if batch["id"] in failed_batch_ids:
            continue
        if batch.get("status") in ("failed", "blocked"):
            failures.append(failure_task(
                "batch",
                batch["id"],
                "批次预检失败" if batch.get("status") == "blocked" else "批次执行失败",
                "批次状态为 %s" % batch.get("status"),
                batch=batch.get("name") or "",
                batchId=batch["id"],
                currentStep="批次预检/执行",
                lastFailedAt=batch.get("updated_at"),
                suggestedActions=["重新运行批次预检", "修复阻塞项后再准备批次"],
                actions=["mark_handled", "manual", "details", "copy"],
            ))
    for key in publish_keys:
        if key.get("status") in ("failed", "blocked", "duplicate", "skipped"):
            product = products.get(key.get("product_id") or "")
            shop = shops.get(key.get("shop_id") or "")
            failures.append(failure_task(
                "publish_key",
                key["idempotency_key"],
                "重复铺货拦截" if key.get("status") == "duplicate" else "真实发布失败",
                key.get("failure_reason") or key.get("result") or key.get("status"),
                product=(product or {}).get("title", ""),
                productId=key.get("product_id") or "",
                market=key.get("market") or "",
                shop=(shop or {}).get("shop_name", ""),
                shopId=key.get("shop_id") or "",
                batchId=key.get("batch_id") or "",
                batch=(batches.get(key.get("batch_id") or "") or {}).get("name", ""),
                currentStep="真实发布结果",
                lastFailedAt=key.get("published_at") or key.get("created_at"),
                suggestedActions=["检查发布结果或重复铺货记录", "必要时转人工确认"],
                actions=["mark_handled", "manual", "details", "copy"],
            ))
    failures.sort(key=lambda item: item.get("lastFailedAt") or 0, reverse=True)
    return {
        "overview": overview,
        "failures": failures[:50],
        "waiting": waiting[:20],
        "recent": recent[:50],
        "shopStats": publish_stats["shopStats"],
        "marketStats": publish_stats["marketStats"],
    }


def resolve_failure_task(payload):
    source = str(payload.get("source") or "")
    item_id = str(payload.get("id") or "")
    action = str(payload.get("action") or "")
    if not source or not item_id or action not in ("retry", "skip", "mark_handled", "manual"):
        raise ValueError("失败任务操作无效")
    if source == "automation_run":
        run = DB.get_run(item_id)
        if not run:
            raise ValueError("任务不存在")
        if action == "retry":
            if int(run["attempts"] or 0) >= 2:
                raise ValueError("该任务已达到最多2次重试限制，请检查页面或配置后新建任务")
            DB.update_run(run["id"], status="queued", error="", attempts=int(run["attempts"] or 0) + 1, resolution="")
            enqueue_automation_run(run["id"])
        elif action == "skip":
            DB.update_run(run["id"], status="skipped", resolution="skipped")
        elif action == "mark_handled":
            DB.update_run(run["id"], resolution="handled")
        elif action == "manual":
            DB.update_run(run["id"], resolution="manual")
        return DB.get_run(item_id)
    if source == "generation_job":
        if action == "retry":
            return retry_generation_job(item_id)
        if action in ("skip", "mark_handled", "manual"):
            status = {"skip": "skipped", "mark_handled": "handled", "manual": "manual"}[action]
            DB.execute("UPDATE generation_jobs SET status=?, updated_at=? WHERE id=?", (status, int(time.time()), item_id))
            return DB.row("SELECT * FROM generation_jobs WHERE id=?", (item_id,))
    if source == "asset":
        if action in ("skip", "mark_handled", "manual"):
            status = {"skip": "skipped", "mark_handled": "handled", "manual": "manual"}[action]
            DB.execute("UPDATE assets SET review_status=? WHERE id=?", (status, item_id))
            return DB.row("SELECT * FROM assets WHERE id=?", (item_id,))
    if source == "publish_key":
        status = {"skip": "skipped", "mark_handled": "handled", "manual": "manual"}.get(action)
        if status:
            DB.execute("UPDATE publish_keys SET status=?, result=?, published_at=? WHERE idempotency_key=?", (status, status, int(time.time()), item_id))
            return DB.row("SELECT * FROM publish_keys WHERE idempotency_key=?", (item_id,))
    if source == "batch" and action in ("skip", "mark_handled", "manual"):
        status = {"skip": "skipped", "mark_handled": "handled", "manual": "manual"}[action]
        DB.execute("UPDATE batches SET status=?, updated_at=? WHERE id=?", (status, int(time.time()), item_id))
        return DB.row("SELECT * FROM batches WHERE id=?", (item_id,))
    raise ValueError("该失败任务不支持此操作")


def reserve_publish_keys(batch):
    products = {item["id"]: item for item in DB.list_products()}
    shops = {item["id"]: item for item in DB.rows("SELECT * FROM shops")}
    duplicates = []
    now = int(time.time())
    with DB.lock, DB.connect() as connection:
        for product_id in batch["product_ids"]:
            product = products[product_id]
            for shop_id in batch["shop_ids"]:
                shop = shops[shop_id]
                key = publish_key_for(product, shop)
                row = connection.execute("SELECT status,batch_id FROM publish_keys WHERE idempotency_key=?", (key,)).fetchone()
                if row and row["batch_id"] != batch["id"] and row["status"] in ("reserved", "published"):
                    duplicates.append("%s → %s" % (product.get("title") or product_id, shop["shop_name"]))
                else:
                    connection.execute(
                        """INSERT INTO publish_keys(idempotency_key,batch_id,status,product_id,shop_id,market,result,failure_reason,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO UPDATE SET
                        batch_id=excluded.batch_id,status=excluded.status,product_id=excluded.product_id,
                        shop_id=excluded.shop_id,market=excluded.market,result=excluded.result,failure_reason=excluded.failure_reason""",
                        (key, batch["id"], "reserved", product_id, shop_id, shop["market"], "已预留", "", now),
                    )
    return duplicates


def classify_selfcheck_steps(checks):
    automatic = {
        "candidate_images": "选择候选后点击“从来源补全选中”，或再次运行自检修复。",
        "candidate_supply_data": "补齐采购价、重量、销量、评分、发货和 SKU 完整度后重新评估。",
        "qualified_candidates": "补齐五国市场样本和目标售价，达到评分与置信度门槛后再采集。",
        "product_pool": "候选达标并完成采集后，系统会创建正式商品。",
        "approved_assets": "上传或生成图片后完成审核，达标商品可由自检修复登记已有主图。",
    }
    manual = {
        "chrome_install": "把 Google Chrome 移到 /Applications，避免 macOS 临时隔离路径变化。",
        "cdp": "点击“启动专用Chrome”，保持该浏览器窗口打开。",
        "miaoshou_login": "在专用 Chrome 中登录妙手 ERP。",
        "alibaba_login": "在专用 Chrome 中登录 1688 并完成必要验证。",
        "plugin": "在专用 Chrome 扩展页加载妙手官方插件，必要时填写扩展 ID。",
        "collection_recipe": "录入采集箱认领动作配方；没有配方时插件采集后需人工认领。",
        "publish_recipe": "录入发布动作配方；真实发布前必须校准页面字段。",
        "image_relay": "填写 AI 中转站 Base URL 和 API Key。",
    }
    result = {"automatic": [], "manual": []}
    for item in checks:
        target = result["automatic"] if item["id"] in automatic else result["manual"]
        guidance = automatic.get(item["id"]) or manual.get(item["id"]) or item["detail"]
        target.append({**item, "guidance": guidance})
    return result


def system_selfcheck():
    checks = []
    integrity = DB.row("PRAGMA integrity_check")
    checks.append({"id": "database", "label": "SQLite数据库", "status": "pass" if integrity and integrity.get("integrity_check") == "ok" else "fail", "detail": (integrity or {}).get("integrity_check", "不可用")})
    try:
        ASSET_DIR.mkdir(parents=True, exist_ok=True)
        probe = ASSET_DIR / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append({"id": "assets", "label": "图片目录读写", "status": "pass", "detail": str(ASSET_DIR)})
    except OSError as exc:
        checks.append({"id": "assets", "label": "图片目录读写", "status": "fail", "detail": str(exc)})
    node_path = Path(str(DB.setting("automation.node_path", "")))
    runner = ROOT / "scripts" / "cdp_runner.mjs"
    checks.append({"id": "node", "label": "自动化运行时", "status": "pass" if node_path.is_file() and runner.is_file() else "fail", "detail": str(node_path)})
    preflight = AUTOMATION.preflight()
    checks.append({"id": "chrome", "label": "正版Chrome", "status": "pass" if preflight["chromeInstalled"] else "warn", "detail": preflight["chromePath"]})
    checks.append({"id": "chrome_install", "label": "Chrome固定安装路径", "status": "pass" if preflight.get("chromeInstallStable") else "warn", "detail": "已固定安装" if preflight.get("chromeInstallStable") else "当前从macOS隔离临时路径运行，建议移入Applications"})
    checks.append({"id": "cdp", "label": "Chrome调试连接", "status": "pass" if preflight["cdpConnected"] else "warn", "detail": "已连接" if preflight["cdpConnected"] else "启动真实任务前需要连接"})
    checks.append({"id": "miaoshou_login", "label": "妙手登录状态", "status": "pass" if preflight["miaoshouLoginVerified"] else "warn", "detail": "已识别登录页面" if preflight["miaoshouLoginVerified"] else "未识别已登录的妙手页面"})
    checks.append({"id": "alibaba_login", "label": "1688登录状态", "status": "pass" if preflight.get("alibabaLoginVerified") else "warn", "detail": "已识别1688页面" if preflight.get("alibabaLoginVerified") else "未识别已登录的1688页面"})
    checks.append({"id": "plugin", "label": "妙手官方插件", "status": "pass" if preflight["pluginVerified"] else "warn", "detail": "已识别插件目标" if preflight["pluginVerified"] else "未识别插件，可填写扩展ID辅助检测"})
    checks.append({"id": "plugin_package", "label": "妙手插件安装包", "status": "pass" if preflight.get("pluginPackageReady") else "warn", "detail": preflight.get("pluginPackagePath") or "未配置解压目录"})
    checks.append({"id": "collection_recipe", "label": "采集箱认领配方", "status": "pass" if DB.setting("automation.collection_recipe", []) else "warn", "detail": "已配置" if DB.setting("automation.collection_recipe", []) else "插件采集后需要人工认领"})
    checks.append({"id": "publish_recipe", "label": "妙手发布配方", "status": "pass" if DB.setting("automation.publish_recipe", []) else "warn", "detail": "已配置" if DB.setting("automation.publish_recipe", []) else "真实发布前必须校准"})
    checks.append({"id": "image_relay", "label": "AI中转站", "status": "pass" if DB.setting("image.base_url", "") and get_secret() else "warn", "detail": "已配置" if DB.setting("image.base_url", "") and get_secret() else "未配置地址或API Key"})
    candidates = [candidate_summary(item) for item in DB.list_candidates()]
    products = DB.list_products()
    image_ready = sum(1 for item in candidates if item.get("image_count") or item.get("images"))
    supply_ready = sum(
        1 for item in candidates
        if item.get("category") and item.get("source_price") and item.get("weight_g")
        and item.get("monthly_sales") and item.get("rating") and item.get("sku_complete")
    )
    qualified = sum(1 for item in candidates if item.get("qualifiedMarkets"))
    approved_products = approved_asset_product_ids()
    checks.append({
        "id": "candidate_pool",
        "label": "候选商品池",
        "status": "pass" if candidates else "warn",
        "detail": "已有 %d 个候选商品" % len(candidates) if candidates else "尚未导入候选商品",
    })
    checks.append({
        "id": "candidate_images",
        "label": "候选主图",
        "status": "pass" if candidates and image_ready == len(candidates) else "warn",
        "detail": "%d/%d 个候选已有图片，%d 个已就绪" % (image_ready, len(candidates), sum(1 for item in candidates if item.get("imageReady"))),
    })
    checks.append({
        "id": "candidate_supply_data",
        "label": "供应评估数据",
        "status": "pass" if candidates and supply_ready == len(candidates) else "warn",
        "detail": "%d/%d 个候选已有价格、重量、销量、评分和SKU完整度" % (supply_ready, len(candidates)),
    })
    checks.append({
        "id": "qualified_candidates",
        "label": "达标候选",
        "status": "pass" if qualified else "warn",
        "detail": "已有 %d 个候选达到自动采集门槛" % qualified if qualified else "暂无达标候选，需要补供应和五国市场数据",
    })
    checks.append({
        "id": "product_pool",
        "label": "正式商品",
        "status": "pass" if products else "warn",
        "detail": "已有 %d 个正式商品" % len(products) if products else "尚未创建正式商品",
    })
    checks.append({
        "id": "approved_assets",
        "label": "图片审核",
        "status": "pass" if products and all(item["id"] in approved_products for item in products) else "warn",
        "detail": "%d/%d 个正式商品有审核通过图片" % (len([item for item in products if item["id"] in approved_products]), len(products)),
    })
    unresolved = [item for item in checks if item["status"] != "pass"]
    return {
        "ok": not any(item["status"] == "fail" for item in checks),
        "readyForLive": all(item["status"] == "pass" for item in checks),
        "checks": checks,
        "nextSteps": classify_selfcheck_steps(unresolved),
        "checkedAt": int(time.time()),
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = "MiaoShouWorkbench/1.0"

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        origin = self.headers.get("Origin", "")
        if self.origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    @staticmethod
    def origin_allowed(origin):
        if not origin:
            return False
        parsed = urlparse(origin)
        return parsed.scheme in ("http", "https") and parsed.hostname in ("127.0.0.1", "localhost", "::1")

    def reject_cross_origin(self):
        origin = self.headers.get("Origin", "")
        if origin and not self.origin_allowed(origin):
            self.send_json({"error": "拒绝非本机网页调用本地接口"}, HTTPStatus.FORBIDDEN)
            return True
        return False

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, content_type, filename=None):
        self.send_response(HTTPStatus.OK)
        self.common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s" % quote(filename))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if self.reject_cross_origin():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.common_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Workbench-Token")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            return self.send_json({"ok": True, "service": "妙手智能选品工作台", "database": "sqlite"})
        if path == "/api/local/status":
            return self.send_json(local_status())
        if path == "/api/config":
            return self.send_json(workbench_config())
        if path == "/api/browser/status":
            return self.send_json(BROWSER.status())
        if path == "/api/platform/status":
            return self.send_json(BROWSER.platform_status())
        if path == "/api/sourcing/current":
            return self.send_json(sourcing_current_status())
        if path == "/api/dashboard":
            candidates = DB.list_candidates()
            threshold = float(DB.setting("evaluation.threshold", 70))
            confidence = float(DB.setting("evaluation.min_confidence", 70))
            qualified = sum(
                any(item["total_score"] >= threshold and item["confidence"] >= confidence and not item["hard_blocks"] for item in candidate["evaluations"])
                for candidate in candidates
            )
            return self.send_json({
                "candidates": len(candidates), "qualified": qualified,
                "products": len(DB.list_products()), "runs": DB.list_runs()[:10], "preflight": AUTOMATION.preflight(),
            })
        if path == "/api/workflow/summary":
            return self.send_json(workflow_summary())
        if path == "/api/candidates":
            query = parse_qs(parsed.query)
            status = (query.get("status") or [""])[0]
            candidates = DB.list_candidates()
            if status in ("new_candidate", "duplicate_skipped"):
                dedupe_candidates([item["id"] for item in candidates])
            if status in ("precheck_passed", "risk_blocked", "low_priority_skipped"):
                precheck_candidates([item["id"] for item in candidates])
                candidates = DB.list_candidates()
            items = filter_candidates_by_status(candidates, status)
            if not status:
                items = [candidate_summary(item) for item in items]
            return self.send_json({"items": items})
        if path == "/api/candidates/dedupe":
            query = parse_qs(parsed.query)
            status = (query.get("status") or [""])[0]
            return self.send_json(dedupe_queue_summary(status))
        if path == "/api/candidates/precheck":
            query = parse_qs(parsed.query)
            status = (query.get("status") or [""])[0]
            all_items = [candidate_summary(item) for item in DB.list_candidates()]
            items = all_items
            if status:
                items = filter_candidates_by_status(DB.list_candidates(), status)
            counts = {key: 0 for key in PRECHECK_STATUS_LABELS}
            for item in all_items:
                counts[item.get("precheckStatus") or "not_checked"] = counts.get(item.get("precheckStatus") or "not_checked", 0) + 1
            return self.send_json({"items": items, "counts": counts, "count": len(items)})
        if path == "/api/evaluations/qualified":
            return self.send_json(qualified_evaluations_summary())
        if path == "/api/collections/queue":
            query = parse_qs(parsed.query)
            status = (query.get("status") or [""])[0]
            return self.send_json(collection_queue_summary(status))
        match = re.match(r"^/api/collections/tasks/(candidate:[a-zA-Z0-9_-]+|[a-zA-Z0-9_-]+)$", path)
        if match:
            try:
                return self.send_json(collection_task_detail(match.group(1)))
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        match = re.match(r"^/api/candidates/([a-zA-Z0-9_-]+)$", path)
        if match:
            item = DB.get_candidate(match.group(1))
            return self.send_json(candidate_summary(item) if item else {"error": "候选商品不存在"}, HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        if path == "/api/products":
            return self.send_json({"items": products_with_workflow_status()})
        match = re.match(r"^/api/products/([a-zA-Z0-9_-]+)/markets$", path)
        if match:
            return self.send_json({"items": DB.market_versions(match.group(1))})
        if path == "/api/shops":
            return self.send_json({"items": DB.rows("SELECT * FROM shops ORDER BY market,shop_name")})
        if path == "/api/assets":
            query = parse_qs(parsed.query)
            return self.send_json({"items": DB.rows("SELECT * FROM assets WHERE product_id=? ORDER BY created_at", ((query.get("productId") or [""])[0],))})
        if path == "/api/images/jobs":
            return self.send_json({"items": DB.rows("SELECT * FROM generation_jobs ORDER BY created_at DESC")})
        if path == "/api/images/summary":
            return self.send_json(image_workbench_summary())
        match = re.match(r"^/api/images/jobs/([a-zA-Z0-9_-]+)$", path)
        if match:
            job = DB.row("SELECT * FROM generation_jobs WHERE id=?", (match.group(1),))
            return self.send_json(job or {"error": "生图任务不存在"}, HTTPStatus.OK if job else HTTPStatus.NOT_FOUND)
        if path == "/api/batches":
            return self.send_json({"items": DB.rows("SELECT * FROM batches ORDER BY created_at DESC")})
        match = re.match(r"^/api/batches/([a-zA-Z0-9_-]+)$", path)
        if match:
            batch = DB.row("SELECT * FROM batches WHERE id=?", (match.group(1),))
            return self.send_json(batch or {"error": "批次不存在"}, HTTPStatus.OK if batch else HTTPStatus.NOT_FOUND)
        match = re.match(r"^/api/batches/([a-zA-Z0-9_-]+)/confirmation$", path)
        if match:
            batch = DB.row("SELECT * FROM batches WHERE id=?", (match.group(1),))
            return self.send_json(batch_confirmation_summary(batch) if batch else {"error": "批次不存在"}, HTTPStatus.OK if batch else HTTPStatus.NOT_FOUND)
        match = re.match(r"^/api/batches/([a-zA-Z0-9_-]+)/report$", path)
        if match:
            batch = DB.row("SELECT * FROM batches WHERE id=?", (match.group(1),))
            return self.send_json(batch_report(batch) if batch else {"error": "批次不存在"}, HTTPStatus.OK if batch else HTTPStatus.NOT_FOUND)
        if path == "/api/runs":
            return self.send_json({"items": DB.list_runs()})
        if path == "/api/publish/results":
            return self.send_json(publish_results_summary())
        match = re.match(r"^/api/runs/([a-zA-Z0-9_-]+)/events$", path)
        if match:
            run = DB.get_run(match.group(1))
            return self.send_json(run or {"error": "任务不存在"}, HTTPStatus.OK if run else HTTPStatus.NOT_FOUND)
        if path == "/api/settings":
            values = DB.settings()
            values["image.has_api_key"] = bool(get_secret())
            return self.send_json(values)
        if path == "/api/automation/preflight":
            return self.send_json(AUTOMATION.preflight())
        if path == "/api/selfcheck":
            return self.send_json(system_selfcheck())
        if path == "/api/export.csv":
            return self.send_bytes(products_to_csv(DB.list_products()).encode("utf-8"), "text/csv; charset=utf-8", "miaoshou-products.csv")
        if path == "/api/export.json":
            return self.send_bytes(json.dumps(DB.list_products(), ensure_ascii=False, indent=2).encode(), "application/json; charset=utf-8", "miaoshou-products.json")
        if path == "/api/image":
            url = (parse_qs(parsed.query).get("url") or [""])[0]
            try:
                data, content_type = fetch_image(url)
                return self.send_bytes(data, content_type)
            except CollectError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if path.startswith("/assets/"):
            return self.serve_file(ASSET_DIR / Path(path).name, cache=True)
        image_match = re.match(r"^/images/([a-zA-Z0-9_-]+)/([^/]+)$", path)
        if image_match:
            candidate_id = image_match.group(1)
            filename = Path(image_match.group(2)).name
            image_path = (DATA_DIR / "images" / candidate_id / filename).resolve()
            try:
                image_path.relative_to((DATA_DIR / "images" / candidate_id).resolve())
            except ValueError:
                return self.send_error(HTTPStatus.NOT_FOUND)
            return self.serve_file(image_path, cache=True)
        if path == "/":
            return self.serve_file(STATIC_DIR / "index.html")
        candidate = (STATIC_DIR / path.lstrip("/")).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return self.send_error(HTTPStatus.NOT_FOUND)
        return self.serve_file(candidate)

    def do_POST(self):
        if self.reject_cross_origin():
            return
        if not is_loopback_client(self):
            return self.send_json({"error": "拒绝非本机写入请求"}, HTTPStatus.FORBIDDEN)
        if not workbench_token_valid(self):
            return self.send_json({"error": "缺少或无效的本地 Workbench Token"}, HTTPStatus.FORBIDDEN)
        path = urlparse(self.path).path
        try:
            payload = json_body(self)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        try:
            return self.route_post(path, payload)
        except (ValueError, CollectError, ImageGatewayError, TextGatewayError, RuntimeError) as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            return self.send_json({"error": "内部错误：%s" % exc}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def route_post(self, path, payload):
        if path == "/api/config":
            return self.send_json(apply_config_to_settings(save_config(DATA_DIR, payload)))

        if path == "/api/browser/start":
            return self.send_json(BROWSER.start())

        if path == "/api/browser/stop":
            return self.send_json(BROWSER.stop())

        if path == "/api/browser/restart":
            return self.send_json(BROWSER.restart())

        if path == "/api/sourcing/start":
            run = SOURCING.start_run()
            enqueue_sourcing_run(run["run_id"])
            return self.send_json(sourcing_current_status(), HTTPStatus.CREATED)

        if path == "/api/sourcing/pause":
            SOURCING.pause()
            return self.send_json(sourcing_current_status())

        if path == "/api/sourcing/resume":
            run = SOURCING.resume()
            if run.get("status") in ("starting_browser", "idle", "waiting_for_manual"):
                enqueue_sourcing_run(run["run_id"])
            return self.send_json(sourcing_current_status())

        if path == "/api/sourcing/stop":
            SOURCING.stop()
            return self.send_json(sourcing_current_status())

        if path == "/api/candidates/import-links":
            raw = payload.get("urls") or []
            if isinstance(raw, str):
                raw = re.split(r"[\s,]+", raw)
            urls = []
            for value in raw:
                if value and normalize_url(value) not in urls:
                    urls.append(normalize_url(value))
            if not urls:
                raise ValueError("请至少提供一个1688商品链接")
            if len(urls) > 200:
                raise ValueError("一次最多导入200个链接")
            items = DB.import_candidates(urls)
            for item in items:
                DB.update_candidate(item["id"], {"source_product_id": source_product_id(item["source_url"])})
            ids = [item["id"] for item in items]
            dedupe_candidates(ids)
            precheck_candidates(ids)
            return self.send_json({"items": [candidate_summary(DB.get_candidate(item["id"])) for item in items]}, HTTPStatus.CREATED)

        if path == "/api/candidates/search":
            keyword = str(payload.get("keyword") or "").strip()
            if not keyword:
                raise ValueError("请输入找品关键词")
            search_url = "https://s.1688.com/selloffer/offer_search.htm?keywords=" + encode_1688_keyword(keyword)
            run = AUTOMATION.create_keyword_search_run(keyword, search_url)
            enqueue_automation_run(run["id"])
            return self.send_json({"keyword": keyword, "searchUrl": search_url, "run": DB.get_run(run["id"])}, HTTPStatus.CREATED)

        if path == "/api/candidates/evaluate":
            ids = payload.get("candidateIds") or []
            if payload.get("inputs"):
                if not ids:
                    ids = [item["id"] for item in DB.list_candidates()]
                results = []
                blocked = []
                for candidate_id in ids:
                    candidate = DB.get_candidate(candidate_id)
                    if not candidate:
                        continue
                    summary = candidate_summary(candidate)
                    if not summary["isReadyToScore"]:
                        blocked.append({
                            "id": candidate_id,
                            "title": summary.get("title") or summary.get("source_product_id") or candidate_id,
                            "missingFields": summary.get("dataCompleteness", {}).get("requiredMissingFields") or summary.get("missingFields") or [],
                            "missingHints": summary.get("dataCompleteness", {}).get("requiredMissingHints") or summary.get("missingHints") or [],
                            "error": "基础数据不完整，不能进入评分",
                        })
                        continue
                    DB.update_candidate(candidate_id, {"status": "评估中"})
                    evaluations = evaluate_candidate(candidate, payload.get("inputs", {}).get(candidate_id, {}), float(DB.setting("evaluation.min_margin", 20)))
                    DB.save_evaluations(candidate_id, evaluations)
                    status = evaluation_status(evaluations, float(DB.setting("evaluation.threshold", 70)), float(DB.setting("evaluation.min_confidence", 70)))
                    DB.update_candidate(candidate_id, {"status": status})
                    results.append(candidate_summary(DB.get_candidate(candidate_id)))
            else:
                results, blocked = evaluate_candidates(ids)
            response = {"items": results, "blocked": blocked}
            if blocked and not results:
                return self.send_json(response, HTTPStatus.BAD_REQUEST)
            return self.send_json(response)

        if path == "/api/candidates/refresh-sources":
            return self.send_json(refresh_candidates_from_sources(payload.get("candidateIds") or []))

        if path == "/api/candidates/dedupe":
            return self.send_json(dedupe_candidates(candidate_ids_from_payload(payload)))

        if path == "/api/candidates/bulk-check":
            return self.send_json(bulk_check_candidates(candidate_ids_from_payload(payload)))

        if path == "/api/candidates/precheck":
            ids = candidate_ids_from_payload(payload)
            return self.send_json(precheck_candidates(ids))

        if path == "/api/candidates/bulk-skip":
            ids = candidate_ids_from_payload(payload)
            if not ids:
                raise ValueError("请先选择候选商品")
            return self.send_json(bulk_skip_candidates(ids))

        if path == "/api/candidates/bulk-delete":
            ids = candidate_ids_from_payload(payload)
            if not ids:
                raise ValueError("请先选择候选商品")
            return self.send_json(bulk_delete_candidates(ids))

        if path == "/api/evaluations/recalculate":
            results, blocked = recalculate_evaluations(candidate_ids_from_payload(payload))
            response = {"items": results, "blocked": blocked}
            if blocked and not results:
                return self.send_json(response, HTTPStatus.BAD_REQUEST)
            return self.send_json(response)

        if path == "/api/selfcheck/repair":
            return self.send_json(selfcheck_repair(payload.get("maxRefresh", 5)))

        if path == "/api/candidates/collect-qualified":
            response = collect_qualified_candidates(payload.get("candidateIds") or [], payload.get("markets") or [], bool(payload.get("review")))
            if response["blocked"] and not response["items"]:
                return self.send_json(response, HTTPStatus.BAD_REQUEST)
            return self.send_json(response)

        if path == "/api/products/collect-qualified":
            response = collect_qualified_candidates(candidate_ids_from_payload(payload), payload.get("markets") or [], bool(payload.get("review")))
            if response["blocked"] and not response["items"]:
                return self.send_json(response, HTTPStatus.BAD_REQUEST)
            return self.send_json(response)

        if path == "/api/products/clean-title":
            ids = candidate_ids_from_payload(payload)
            title = str(payload.get("title") or "").strip()
            if ids:
                result = clean_titles_for_candidates(ids)
                return self.send_json(result)
            if not title:
                raise ValueError("请提供 title 或 candidateIds")
            result = TITLE_CLEANER.clean(title)
            if hasattr(DB, "save_title_cleaning_record"):
                result["cleaned_at"] = int(time.time())
                DB.save_title_cleaning_record(title_clean_record_payload({}, result))
            return self.send_json(result)

        if path == "/api/collections/bulk-action":
            return self.send_json(bulk_collection_action(payload))

        match = re.match(r"^/api/candidates/([a-zA-Z0-9_-]+)$", path)
        if match:
            item = DB.update_candidate(match.group(1), payload)
            if not item:
                return self.send_json({"error": "候选商品不存在"}, HTTPStatus.NOT_FOUND)
            return self.send_json(item)

        if path == "/api/collect":
            product = scrape_product(str(payload.get("url") or ""))
            return self.send_json(product)

        if path == "/api/products":
            product = DB.save_product(payload)
            create_market_versions(product["id"])
            return self.send_json(product, HTTPStatus.CREATED)

        match = re.match(r"^/api/products/([a-zA-Z0-9_-]+)/markets/([A-Z]{2})$", path)
        if match:
            if match.group(2) not in MARKETS:
                raise ValueError("国家代码无效")
            version = DB.save_market_version(match.group(1), match.group(2), payload)
            if not version:
                raise ValueError("商品国家版本不存在")
            return self.send_json(version)

        match = re.match(r"^/api/products/([a-zA-Z0-9_-]+)/localize$", path)
        if match:
            product = DB.get_product(match.group(1))
            if not product:
                raise ValueError("商品不存在")
            localized = localize(DB.settings(), product.get("title", ""), product.get("notes", ""), product.get("category", ""))
            for market in ("MY", "PH", "SG"):
                DB.save_market_version(product["id"], market, localized["en"])
            DB.save_market_version(product["id"], "TH", localized["th"])
            DB.save_market_version(product["id"], "VN", localized["vi"])
            return self.send_json({"items": DB.market_versions(product["id"])})

        match = re.match(r"^/api/candidates/([a-zA-Z0-9_-]+)/refresh-source$", path)
        if match:
            item = refresh_candidate_from_source(match.group(1))
            if not item:
                raise ValueError("候选商品不存在")
            return self.send_json(item)

        if path == "/api/assets":
            url = save_data_image(payload.get("dataUrl"))
            product_id = str(payload.get("productId") or "")
            if product_id:
                if not DB.get_product(product_id):
                    raise ValueError("商品不存在")
                asset_id = uuid.uuid4().hex
                approved = int(bool(payload.get("approved", False)))
                review_status = "approved" if approved else "pending"
                DB.execute(
                    "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (asset_id, product_id, url, payload.get("kind") or "uploaded", approved, review_status, "", "", int(time.time())),
                )
                return self.send_json(DB.row("SELECT * FROM assets WHERE id=?", (asset_id,)), HTTPStatus.CREATED)
            return self.send_json({"url": url}, HTTPStatus.CREATED)

        if path == "/api/images/generate":
            product = DB.get_product(str(payload.get("productId") or ""))
            job = create_generation_job(
                product,
                str(payload.get("preset") or "standard"),
                str(payload.get("extraPrompt") or ""),
                payload.get("kinds"),
            )
            return self.send_json(job, HTTPStatus.CREATED)

        if path == "/api/images/download":
            return self.send_json(download_candidate_images(candidate_ids_from_payload(payload)))

        if path == "/api/images/analyze":
            return self.send_json(analyze_candidate_images_for_ids(candidate_ids_from_payload(payload)))

        if path == "/api/images/auto-process":
            return self.send_json(auto_process_candidate_images(candidate_ids_from_payload(payload)))

        if path == "/api/images/bulk-generate":
            response = bulk_generate_images(payload)
            return self.send_json(response, HTTPStatus.CREATED if response["items"] else HTTPStatus.BAD_REQUEST)

        if path == "/api/images/jobs/retry-failed":
            return self.send_json(retry_failed_generation_jobs(payload))

        if path == "/api/images/assets/bulk-approve":
            return self.send_json(bulk_approve_assets(payload))

        if path == "/api/images/assets/bulk-reject":
            return self.send_json(bulk_reject_assets(payload))

        match = re.match(r"^/api/images/([a-zA-Z0-9_-]+)/approve$", path)
        if match:
            return self.send_json(approve_asset(match.group(1)))

        match = re.match(r"^/api/images/([a-zA-Z0-9_-]+)/reject$", path)
        if match:
            return self.send_json(reject_asset(match.group(1), payload.get("reason") or "其他"))

        match = re.match(r"^/api/images/jobs/([a-zA-Z0-9_-]+)/retry$", path)
        if match:
            return self.send_json(retry_generation_job(match.group(1)))

        if path == "/api/shops":
            market = str(payload.get("market") or "")
            if market not in MARKETS:
                raise ValueError("店铺国家无效")
            shop_id = str(payload.get("id") or uuid.uuid4().hex)
            DB.execute(
                """INSERT INTO shops(id,account_name,entity_name,shop_name,market,warehouse,default_inventory,price_multiplier,enabled)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET account_name=excluded.account_name,
                entity_name=excluded.entity_name,shop_name=excluded.shop_name,market=excluded.market,warehouse=excluded.warehouse,
                default_inventory=excluded.default_inventory,price_multiplier=excluded.price_multiplier,enabled=excluded.enabled""",
                (shop_id, payload.get("accountName", ""), payload.get("entityName", ""), payload.get("shopName", ""), market,
                 payload.get("warehouse", ""), int(payload.get("defaultInventory") or 20), float(payload.get("priceMultiplier") or 1), int(payload.get("enabled", True))),
            )
            return self.send_json(DB.row("SELECT * FROM shops WHERE id=?", (shop_id,)), HTTPStatus.CREATED)

        if path in ("/api/batches/preview", "/api/batches/precheck"):
            preview = batch_preflight({
                "id": payload.get("id") or "",
                "productIds": payload.get("productIds") or [],
                "shopIds": payload.get("shopIds") or [],
                "dryRun": payload.get("dryRun", True),
            })
            return self.send_json(preview)

        if path in ("/api/batches", "/api/batches/create"):
            reject_unsafe_publish_payload(payload)
            batch, preview, error = create_batch_from_payload(payload)
            if error:
                return self.send_json({"error": error, "preflight": preview}, HTTPStatus.BAD_REQUEST)
            return self.send_json({"batch": batch, "preflight": preview} if path == "/api/batches/create" else batch, HTTPStatus.CREATED)

        match = re.match(r"^/api/batches/([a-zA-Z0-9_-]+)/(prepare|confirm)$", path)
        if match:
            batch = DB.row("SELECT * FROM batches WHERE id=?", (match.group(1),))
            if not batch:
                raise ValueError("批次不存在")
            if match.group(2) == "prepare":
                preview = batch_preflight(batch)
                DB.execute(
                    "UPDATE batches SET summary=?,updated_at=? WHERE id=?",
                    (json.dumps(batch_summary_from_preview(preview), ensure_ascii=False), int(time.time()), batch["id"]),
                )
                if not preview["ready"]:
                    errors = [item["message"] for item in preview["risks"] if item["severity"] == "error"]
                    return self.send_json({"error": "批次预检失败：" + "；".join(errors[:10]), "preflight": preview}, HTTPStatus.BAD_REQUEST)
                duplicates = reserve_publish_keys(batch)
                if duplicates:
                    raise ValueError("检测到重复铺货：" + "；".join(duplicates[:10]))
                run = AUTOMATION.create_publish_run(batch["id"])
                DB.update_run(run["id"], context={"phase": "prepare"})
                DB.execute("UPDATE batches SET status='preparing',updated_at=? WHERE id=?", (int(time.time()), batch["id"]))
                enqueue_automation_run(run["id"])
                return self.send_json(DB.get_run(run["id"]))
            return self.send_json(confirm_batch(batch["id"], payload))

        match = re.match(r"^/api/runs/([a-zA-Z0-9_-]+)/retry$", path)
        if match:
            run = DB.get_run(match.group(1))
            if not run:
                raise ValueError("任务不存在")
            if int(run["attempts"] or 0) >= 2:
                raise ValueError("该任务已达到最多2次重试限制，请检查页面或配置后新建任务")
            DB.update_run(run["id"], status="queued", error="", attempts=int(run["attempts"] or 0) + 1, resolution="")
            enqueue_automation_run(run["id"])
            return self.send_json(DB.get_run(run["id"]))

        if path == "/api/failures/action":
            result = resolve_failure_task(payload)
            return self.send_json({"item": result, "summary": publish_results_summary()})

        if path == "/api/settings":
            values = dict(payload)
            api_key = values.pop("image.api_key", "")
            if api_key:
                set_secret(api_key)
            recipe = values.get("automation.publish_recipe")
            if recipe is not None:
                AUTOMATION.ensure_publish_allowed(recipe, "发布动作配方")
            allowed_prefixes = ("evaluation.", "automation.", "image.", "text.", "market.")
            DB.set_settings({key: value for key, value in values.items() if key.startswith(allowed_prefixes)})
            return self.send_json({"ok": True})

        if path == "/api/automation/launch":
            return self.send_json(BROWSER.start())
        return self.send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        if self.reject_cross_origin():
            return
        if not is_loopback_client(self):
            return self.send_json({"error": "拒绝非本机写入请求"}, HTTPStatus.FORBIDDEN)
        if not workbench_token_valid(self):
            return self.send_json({"error": "缺少或无效的本地 Workbench Token"}, HTTPStatus.FORBIDDEN)
        path = urlparse(self.path).path
        match = re.match(r"^/api/products/([a-zA-Z0-9_-]+)$", path)
        if match and DB.delete_product(match.group(1)):
            return self.send_json({"ok": True})
        return self.send_json({"error": "资源不存在"}, HTTPStatus.NOT_FOUND)

    def serve_file(self, path, cache=False):
        if not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.common_headers()
        self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400" if cache else "no-cache")
        self.end_headers()
        self.wfile.write(body)


def main():
    initialize()
    recover_background_jobs()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer((host, port), AppHandler)
    print("妙手智能选品工作台已启动：http://%s:%s" % (host, port))
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
