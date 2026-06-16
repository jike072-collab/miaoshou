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
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from lib.automation import AutomationEngine, source_product_id
from lib.collector import CollectError, fetch_image, scrape_product
from lib.database import Database, MARKETS
from lib.evaluation import evaluate_candidate, evaluation_status
from lib.image_gateway import ImageGatewayError, generate
from lib.keychain import get_secret, set_secret
from lib.prompts import PRESETS, build_prompts
from lib.text_gateway import TextGatewayError, localize


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.environ.get("WORKBENCH_DATA_DIR", str(ROOT / "data"))).resolve()
ASSET_DIR = DATA_DIR / "assets"
DB = Database(DATA_DIR / "workbench.db")
AUTOMATION = AutomationEngine(DB, DATA_DIR)
RUN_LOCK = threading.Lock()
ACTIVE_RUNS = set()
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


def initialize():
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    DB.migrate_products_json(DATA_DIR / "products.json")
    DB.execute("UPDATE automation_runs SET status='queued',error='服务重启后等待恢复' WHERE status IN ('running','preparing')")
    DB.execute("UPDATE generation_jobs SET status='queued',error='服务重启后等待恢复' WHERE status='running'")


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
    evaluations = candidate.get("evaluations") or []
    threshold = float(DB.setting("evaluation.threshold", 70))
    confidence = float(DB.setting("evaluation.min_confidence", 70))
    candidate["qualifiedMarkets"] = [
        item["market"] for item in evaluations
        if item["total_score"] >= threshold and item["confidence"] >= confidence and not item["hard_blocks"]
    ]
    candidate["bestScore"] = max([item["total_score"] for item in evaluations] or [0])
    return candidate


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
            items.append(refresh_candidate_from_source(candidate_id))
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
    results = []
    for candidate_id in ids:
        candidate = DB.get_candidate(candidate_id)
        if not candidate:
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
    return results


def source_image_bytes(url):
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
        DB.execute("UPDATE generation_jobs SET status='running',error='',updated_at=? WHERE id=?", (int(time.time()), job_id))
        completed = int(job.get("completed_count") or 0)
        try:
            if not product:
                raise ImageGatewayError("商品不存在")
            if not prompts:
                raise ImageGatewayError("生图任务缺少持久化提示词")
            source, source_name = source_image_bytes(product.get("mainImage") or "")
            settings = DB.settings()
            retries = max(0, int(settings.get("image.retries") or 0))
            for index, prompt in enumerate(prompts[completed:], start=completed):
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
                    "INSERT INTO assets(id,product_id,url,kind,approved,prompt,created_at) VALUES (?,?,?,?,?,?,?)",
                    (asset_id, product["id"], "/assets/" + filename, "generated", 0, prompt, int(time.time())),
                )
                completed += 1
                DB.execute("UPDATE generation_jobs SET completed_count=?, updated_at=? WHERE id=?", (completed, int(time.time()), job_id))
            DB.execute("UPDATE generation_jobs SET status='awaiting_approval',error='',updated_at=? WHERE id=?", (int(time.time()), job_id))
        except Exception as exc:
            DB.execute(
                "UPDATE generation_jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                (str(exc), int(time.time()), job_id),
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
    images = candidate.get("images") or []
    product = DB.save_product({
        "candidateId": candidate_id,
        "sourceProductId": candidate.get("source_product_id") or "",
        "sourceUrl": candidate.get("source_url") or "",
        "title": candidate.get("title") or "1688商品 %s" % (candidate.get("source_product_id") or ""),
        "category": candidate.get("category") or "",
        "sourcePrice": candidate.get("source_price") or 0,
        "costPrice": candidate.get("source_price") or 0,
        "weightG": candidate.get("weight_g") or 0,
        "images": images,
        "mainImage": images[0] if images else "",
        "status": "待图片审核",
    })
    create_market_versions(product["id"])
    return product


def ensure_approved_asset_for_product(product):
    existing = DB.row("SELECT * FROM assets WHERE product_id=? AND approved=1 LIMIT 1", (product["id"],))
    if existing:
        return existing
    image = product.get("mainImage") or (product.get("images") or [""])[0]
    if not image:
        return None
    if image.startswith("/assets/"):
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
        "INSERT INTO assets(id,product_id,url,kind,approved,prompt,created_at) VALUES (?,?,?,?,?,?,?)",
        (asset_id, product["id"], url, "source", 1, "自检自动登记的候选主图", int(time.time())),
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

    evaluated = evaluate_candidates([item["id"] for item in DB.list_candidates()])
    if evaluated:
        actions.append("重新评估 %d 个候选" % len(evaluated))

    products_before = len(DB.list_products())
    for candidate in DB.list_candidates():
        summary = candidate_summary(candidate)
        if summary.get("qualifiedMarkets"):
            ensure_product_from_candidate(summary["id"])
    products_after = DB.list_products()
    created = len(products_after) - products_before
    if created:
        actions.append("从达标候选创建 %d 个正式商品" % created)

    approved_count = 0
    for product in products_after:
        if DB.row("SELECT id FROM assets WHERE product_id=? AND approved=1 LIMIT 1", (product["id"],)):
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
        result = AUTOMATION.confirm_publish(run_id) if confirm else AUTOMATION.run(run_id)
        if result and result.get("kind") == "collection" and result.get("status") == "completed":
            ensure_product_from_candidate(result.get("candidate_id"))
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
                DB.execute("UPDATE publish_keys SET status=? WHERE batch_id=?", (key_status, result["batch_id"]))
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


def recover_background_jobs():
    for job in DB.rows("SELECT id FROM generation_jobs WHERE status='queued'"):
        enqueue_generation(job["id"])
    for run in DB.rows("SELECT id FROM automation_runs WHERE status='queued'"):
        enqueue_automation_run(run["id"])


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
    errors = []
    products = {item["id"]: item for item in DB.list_products() if item["id"] in batch["product_ids"]}
    shops = {item["id"]: item for item in DB.rows("SELECT * FROM shops") if item["id"] in batch["shop_ids"]}
    approved = {item["product_id"] for item in DB.rows("SELECT DISTINCT product_id FROM assets WHERE approved=1")}
    for product_id in batch["product_ids"]:
        product = products.get(product_id)
        if not product:
            errors.append("商品 %s 不存在" % product_id)
            continue
        if product_id not in approved:
            errors.append("%s 缺少审核通过的图片" % (product.get("title") or product_id))
        versions = {item["market"]: item for item in DB.market_versions(product_id)}
        for shop_id in batch["shop_ids"]:
            shop = shops.get(shop_id)
            if not shop:
                errors.append("店铺 %s 不存在" % shop_id)
                continue
            version = versions.get(shop["market"])
            prefix = "%s → %s" % (product.get("title") or product_id, shop["shop_name"])
            if not version:
                errors.append(prefix + " 缺少国家版本")
                continue
            if version["blocked"]:
                errors.append(prefix + " 被风险规则拦截")
            if not version["title"].strip():
                errors.append(prefix + " 缺少本地标题")
            if float(version["sale_price"] or 0) <= 0:
                errors.append(prefix + " 缺少售价")
            warehouse = version["warehouse"].strip() or shop["warehouse"].strip()
            inventory = int(version["inventory"] or shop["default_inventory"] or 0)
            if not warehouse:
                errors.append(prefix + " 缺少仓库")
            if inventory <= 0:
                errors.append(prefix + " 库存必须大于0")
    return errors


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
                key = "%s|%s|%s|%s" % (
                    product.get("sourceProductId") or product.get("sourceUrl"), product.get("sku") or product["id"],
                    shop["account_name"], shop["shop_name"],
                )
                row = connection.execute("SELECT status,batch_id FROM publish_keys WHERE idempotency_key=?", (key,)).fetchone()
                if row and row["batch_id"] != batch["id"] and row["status"] in ("reserved", "published"):
                    duplicates.append("%s → %s" % (product.get("title") or product_id, shop["shop_name"]))
                else:
                    connection.execute(
                        "INSERT INTO publish_keys(idempotency_key,batch_id,status,created_at) VALUES (?,?,?,?) ON CONFLICT(idempotency_key) DO UPDATE SET batch_id=excluded.batch_id,status=excluded.status",
                        (key, batch["id"], "reserved", now),
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
    approved_products = {
        row["product_id"] for row in DB.rows("SELECT DISTINCT product_id FROM assets WHERE approved=1")
    }
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
        "detail": "%d/%d 个候选已有图片" % (image_ready, len(candidates)),
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            return self.send_json({"ok": True, "service": "妙手智能选品工作台", "database": "sqlite"})
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
        if path == "/api/candidates":
            return self.send_json({"items": [candidate_summary(item) for item in DB.list_candidates()]})
        match = re.match(r"^/api/candidates/([a-zA-Z0-9_-]+)$", path)
        if match:
            item = DB.get_candidate(match.group(1))
            return self.send_json(candidate_summary(item) if item else {"error": "候选商品不存在"}, HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        if path == "/api/products":
            return self.send_json({"items": DB.list_products()})
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
        if path == "/api/runs":
            return self.send_json({"items": DB.list_runs()})
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
                for candidate_id in ids:
                    candidate = DB.get_candidate(candidate_id)
                    if not candidate:
                        continue
                    DB.update_candidate(candidate_id, {"status": "评估中"})
                    evaluations = evaluate_candidate(candidate, payload.get("inputs", {}).get(candidate_id, {}), float(DB.setting("evaluation.min_margin", 20)))
                    DB.save_evaluations(candidate_id, evaluations)
                    status = evaluation_status(evaluations, float(DB.setting("evaluation.threshold", 70)), float(DB.setting("evaluation.min_confidence", 70)))
                    DB.update_candidate(candidate_id, {"status": status})
                    results.append(candidate_summary(DB.get_candidate(candidate_id)))
            else:
                results = evaluate_candidates(ids)
            return self.send_json({"items": results})

        if path == "/api/candidates/refresh-sources":
            return self.send_json(refresh_candidates_from_sources(payload.get("candidateIds") or []))

        if path == "/api/selfcheck/repair":
            return self.send_json(selfcheck_repair(payload.get("maxRefresh", 5)))

        if path == "/api/candidates/collect-qualified":
            threshold = float(DB.setting("evaluation.threshold", 70))
            confidence = float(DB.setting("evaluation.min_confidence", 70))
            requested = set(payload.get("candidateIds") or [])
            runs = []
            for candidate in DB.list_candidates():
                if requested and candidate["id"] not in requested:
                    continue
                qualifies = any(
                    item["total_score"] >= threshold and item["confidence"] >= confidence and not item["hard_blocks"]
                    for item in candidate["evaluations"]
                )
                if not qualifies:
                    continue
                duplicate = DB.row("SELECT id FROM automation_runs WHERE candidate_id=? AND kind='collection' AND status NOT IN ('failed','blocked')", (candidate["id"],))
                if duplicate:
                    continue
                DB.update_candidate(candidate["id"], {"status": "插件采集中", "collection_channel": "plugin_first"})
                run = AUTOMATION.create_collection_run(candidate)
                enqueue_automation_run(run["id"])
                runs.append(DB.get_run(run["id"]))
            return self.send_json({"items": runs})

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
                DB.execute(
                    "INSERT INTO assets(id,product_id,url,kind,approved,prompt,created_at) VALUES (?,?,?,?,?,?,?)",
                    (asset_id, product_id, url, payload.get("kind") or "uploaded", int(bool(payload.get("approved", True))), "", int(time.time())),
                )
                return self.send_json(DB.row("SELECT * FROM assets WHERE id=?", (asset_id,)), HTTPStatus.CREATED)
            return self.send_json({"url": url}, HTTPStatus.CREATED)

        if path == "/api/images/generate":
            product = DB.get_product(str(payload.get("productId") or ""))
            if not product:
                raise ValueError("商品不存在")
            if not product.get("mainImage"):
                raise ValueError("商品没有可用主图")
            preset = str(payload.get("preset") or "standard")
            custom = payload.get("kinds") if preset == "custom" else None
            prompts = build_prompts(product.get("category"), preset, custom, str(payload.get("extraPrompt") or ""))
            job_id = uuid.uuid4().hex
            now = int(time.time())
            DB.execute(
                "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (job_id, product["id"], preset, "queued", len(prompts), json.dumps({"prompts": prompts}, ensure_ascii=False), now, now),
            )
            enqueue_generation(job_id)
            return self.send_json(DB.row("SELECT * FROM generation_jobs WHERE id=?", (job_id,)), HTTPStatus.CREATED)

        match = re.match(r"^/api/images/([a-zA-Z0-9_-]+)/approve$", path)
        if match:
            asset = DB.row("SELECT * FROM assets WHERE id=?", (match.group(1),))
            if not asset:
                raise ValueError("图片不存在")
            DB.execute("UPDATE assets SET approved=1 WHERE id=?", (asset["id"],))
            return self.send_json(DB.row("SELECT * FROM assets WHERE id=?", (asset["id"],)))

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

        if path == "/api/batches":
            product_ids = list(dict.fromkeys(payload.get("productIds") or []))
            shop_ids = list(dict.fromkeys(payload.get("shopIds") or []))
            if not product_ids or not shop_ids:
                raise ValueError("批次必须选择商品和店铺")
            if len(product_ids) > 50 or len(shop_ids) > 20:
                raise ValueError("单批最多50款商品和20家店铺")
            batch_id = uuid.uuid4().hex
            now = int(time.time())
            summary = {"products": len(product_ids), "shops": len(shop_ids), "publishTasks": len(product_ids) * len(shop_ids)}
            DB.execute(
                "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (batch_id, payload.get("name") or "铺货批次", "draft", int(payload.get("dryRun", True)), json.dumps(product_ids), json.dumps(shop_ids), json.dumps(summary), now, now),
            )
            return self.send_json(DB.row("SELECT * FROM batches WHERE id=?", (batch_id,)), HTTPStatus.CREATED)

        match = re.match(r"^/api/batches/([a-zA-Z0-9_-]+)/(prepare|confirm)$", path)
        if match:
            batch = DB.row("SELECT * FROM batches WHERE id=?", (match.group(1),))
            if not batch:
                raise ValueError("批次不存在")
            if match.group(2) == "prepare":
                errors = validate_batch(batch)
                if errors:
                    raise ValueError("批次校验失败：" + "；".join(errors[:10]))
                duplicates = reserve_publish_keys(batch)
                if duplicates:
                    raise ValueError("检测到重复铺货：" + "；".join(duplicates[:10]))
                run = AUTOMATION.create_publish_run(batch["id"])
                DB.update_run(run["id"], context={"phase": "prepare"})
                DB.execute("UPDATE batches SET status='preparing',updated_at=? WHERE id=?", (int(time.time()), batch["id"]))
                enqueue_automation_run(run["id"])
                return self.send_json(DB.get_run(run["id"]))
            run = DB.row("SELECT * FROM automation_runs WHERE batch_id=? AND kind='publish' ORDER BY created_at DESC LIMIT 1", (batch["id"],))
            if not run or run["status"] != "waiting_confirmation":
                raise ValueError("批次尚未完成发布前准备，不能确认")
            now = int(time.time())
            DB.execute("UPDATE batches SET status='confirmed',confirmed_at=?,updated_at=? WHERE id=?", (now, now, batch["id"]))
            context = {**(run.get("context") or {}), "phase": "confirm"}
            DB.update_run(run["id"], status="queued", error="", context=context)
            enqueue_automation_run(run["id"], confirm=True)
            return self.send_json({"batch": DB.row("SELECT * FROM batches WHERE id=?", (batch["id"],)), "run": DB.get_run(run["id"])})

        match = re.match(r"^/api/runs/([a-zA-Z0-9_-]+)/retry$", path)
        if match:
            run = DB.get_run(match.group(1))
            if not run:
                raise ValueError("任务不存在")
            if int(run["attempts"] or 0) >= 2:
                raise ValueError("该任务已达到最多2次重试限制，请检查页面或配置后新建任务")
            DB.update_run(run["id"], status="queued", error="", attempts=int(run["attempts"] or 0) + 1)
            enqueue_automation_run(run["id"])
            return self.send_json(DB.get_run(run["id"]))

        if path == "/api/settings":
            values = dict(payload)
            api_key = values.pop("image.api_key", "")
            if api_key:
                set_secret(api_key)
            allowed_prefixes = ("evaluation.", "automation.", "image.", "text.", "market.")
            DB.set_settings({key: value for key, value in values.items() if key.startswith(allowed_prefixes)})
            return self.send_json({"ok": True})

        if path == "/api/automation/launch":
            return self.send_json(AUTOMATION.launch_chrome())
        return self.send_json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        if self.reject_cross_origin():
            return
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
