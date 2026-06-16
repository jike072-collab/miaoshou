"""Real 1688 search adapter backed by the dedicated Chrome/CDP session."""

import json
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

from lib.automation import source_product_id
from lib.browser_manager import detect_alibaba_login, detect_verification
from lib.local_config import load_config


SOURCING_ACTIVE_STATUSES = {
    "starting_browser",
    "checking_login",
    "searching",
    "extracting_results",
    "saving_candidates",
}


class ManualInterventionRequired(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status or {}


class Real1688Adapter:
    def __init__(self, database, data_dir, browser_manager):
        self.db = database
        self.data_dir = Path(data_dir)
        self.browser = browser_manager
        self.dedupe_callback = None

    def config(self):
        return load_config(self.data_dir)

    def search_url(self, keyword, page=1):
        page = max(1, int(page or 1))
        encoded = quote(str(keyword or "").encode("gbk"))
        url = "https://s.1688.com/selloffer/offer_search.htm?keywords=%s" % encoded
        if page > 1:
            url += "&beginPage=%d" % page
        return url

    def normalize_limits(self):
        config = self.config()
        keywords = [str(item).strip() for item in config.get("keywords", []) if str(item).strip()]
        return {
            "keywords": keywords,
            "max_pages_per_keyword": min(max(1, int(config.get("max_pages_per_keyword") or 1)), 10),
            "max_items_per_run": min(max(1, int(config.get("max_items_per_run") or 10)), 50),
        }

    def latest_run(self):
        return self.db.latest_sourcing_run()

    def active_run(self):
        run = self.latest_run()
        if run and run.get("status") in SOURCING_ACTIVE_STATUSES:
            return run
        return None

    def idle_run(self):
        return {
            "run_id": "",
            "status": "idle",
            "current_keyword": "",
            "current_page": 0,
            "found_count": 0,
            "saved_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "started_at": None,
            "finished_at": None,
            "error": "",
        }

    def start_run(self):
        active = self.active_run()
        if active:
            return active
        run = self.db.create_sourcing_run()
        return self.db.update_sourcing_run(run["run_id"], status="starting_browser", error="")

    def pause(self):
        run = self.latest_run()
        if not run:
            return self.db.create_sourcing_run()
        if run.get("status") in ("completed", "failed", "stopped"):
            return run
        return self.db.update_sourcing_run(run["run_id"], status="waiting_for_manual", error="用户暂停")

    def resume(self):
        run = self.latest_run()
        if not run:
            return self.start_run()
        if run.get("status") == "waiting_for_manual":
            return self.db.update_sourcing_run(run["run_id"], status="starting_browser", error="")
        return run

    def stop(self):
        run = self.latest_run()
        if not run:
            run = self.db.create_sourcing_run()
        return self.db.update_sourcing_run(run["run_id"], status="stopped", finished_at=int(time.time()), error="用户停止")

    def current(self):
        return self.latest_run() or self.idle_run()

    def ensure_alibaba_ready(self, run_id):
        self.db.update_sourcing_run(run_id, status="starting_browser")
        browser_status = self.browser.start_alibaba()
        if not browser_status.get("cdp_ready"):
            raise ManualInterventionRequired("专用 Chrome 未连接，请启动浏览器后重新检测", browser_status)
        self.db.update_sourcing_run(run_id, status="checking_login")
        probe = self.browser.engine.cdp_probe(self.browser.debug_port())
        pages = probe.get("pages") or []
        verification = detect_verification(pages)
        alibaba = detect_alibaba_login(pages)
        if verification.get("detected"):
            raise ManualInterventionRequired("检测到验证码/人机/短信验证，请手动完成后继续", {
                "verification": verification,
                "pages": pages,
            })
        if alibaba.get("needs_login"):
            raise ManualInterventionRequired("请在专用 Chrome 中手动完成 1688 登录后继续", {
                "alibaba": alibaba,
                "pages": pages,
            })
        return True

    def run_once(self, run_id=None):
        run = self.db.get_sourcing_run(run_id) if run_id else self.current()
        run_id = run["run_id"]
        limits = self.normalize_limits()
        if not limits["keywords"]:
            return self.db.update_sourcing_run(
                run_id,
                status="failed",
                finished_at=int(time.time()),
                error="data/config.json 中未配置 keywords",
            )
        try:
            self.ensure_alibaba_ready(run_id)
            found = int(run.get("found_count") or 0)
            saved = int(run.get("saved_count") or 0)
            skipped = int(run.get("skipped_count") or 0)
            failed = int(run.get("failed_count") or 0)
            remaining = limits["max_items_per_run"] - saved
            for keyword in limits["keywords"]:
                if remaining <= 0:
                    break
                for page in range(1, limits["max_pages_per_keyword"] + 1):
                    if remaining <= 0:
                        break
                    current_run = self.db.get_sourcing_run(run_id)
                    if current_run.get("status") in ("stopped", "waiting_for_manual"):
                        return current_run
                    self.db.update_sourcing_run(run_id, status="searching", current_keyword=keyword, current_page=page)
                    result = self.extract(run_id, keyword, page, remaining)
                    if result.get("verification_required") or result.get("login_required"):
                        raise ManualInterventionRequired(result.get("error") or "1688 需要人工处理", result)
                    items = result.get("items") or []
                    found += len(items)
                    self.db.update_sourcing_run(run_id, status="saving_candidates", found_count=found)
                    saved_now, skipped_now, failed_now = self.save_results(items, keyword)
                    saved += saved_now
                    skipped += skipped_now
                    failed += failed_now
                    remaining = limits["max_items_per_run"] - saved
                    self.db.update_sourcing_run(
                        run_id,
                        found_count=found,
                        saved_count=saved,
                        skipped_count=skipped,
                        failed_count=failed,
                    )
                    time.sleep(1.2)
            return self.db.update_sourcing_run(run_id, status="completed", finished_at=int(time.time()), error="")
        except ManualInterventionRequired as exc:
            return self.db.update_sourcing_run(
                run_id,
                status="waiting_for_manual",
                finished_at=None,
                error=str(exc),
            )
        except Exception as exc:
            return self.db.update_sourcing_run(
                run_id,
                status="failed",
                finished_at=int(time.time()),
                error=str(exc),
            )

    def extract(self, run_id, keyword, page, limit):
        self.db.update_sourcing_run(run_id, status="extracting_results")
        payload = {
            "port": self.browser.debug_port(),
            "keyword": keyword,
            "page": page,
            "limit": limit,
            "url": self.search_url(keyword, page),
        }
        node_path = self.db.setting("automation.node_path", "node")
        script = Path(__file__).resolve().parent.parent / "scripts" / "real1688_search.mjs"
        result = subprocess.run(
            [node_path, str(script), json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        response = json.loads(lines[-1]) if lines else {}
        if result.returncode != 0 and not response:
            raise RuntimeError(result.stderr.strip() or "1688 搜索执行失败")
        if response and not response.get("ok", False):
            raise RuntimeError(response.get("error") or result.stderr.strip() or "1688 搜索执行失败")
        return response

    def save_results(self, items, keyword):
        saved = 0
        skipped = 0
        failed = 0
        for item in items:
            try:
                url = item.get("url") or item.get("source_url") or ""
                offer_id = item.get("offer_id") or source_product_id(url)
                if not url or not offer_id:
                    skipped += 1
                    continue
                existing = self.db.row(
                    "SELECT id FROM candidates WHERE source_url=? OR source_product_id=? LIMIT 1",
                    (url, offer_id),
                )
                if existing:
                    candidate = self.db.get_candidate(existing["id"])
                else:
                    candidates = self.db.import_candidates([url], keyword=keyword)
                    candidate = candidates[0] if candidates else None
                if not candidate:
                    failed += 1
                    continue
                images = [item.get("main_image_url") or item.get("image") or ""]
                updates = {
                    "source_product_id": offer_id,
                    "keyword": keyword,
                    "title": item.get("title") or candidate.get("title") or "",
                    "category": item.get("category") or candidate.get("category") or "",
                    "source_price": float(item.get("price") or 0),
                    "min_order": int(item.get("min_order") or 0),
                    "sales_text": item.get("sales_text") or "",
                    "supplier_name": item.get("supplier_name") or "",
                    "shop_url": item.get("shop_url") or "",
                    "origin_place": item.get("origin_place") or "",
                    "monthly_sales": int(item.get("monthly_sales") or 0),
                    "images": [value for value in images if value],
                    "image_count": len([value for value in images if value]),
                    "search_page": int(item.get("search_page") or 0),
                    "search_rank": int(item.get("search_rank") or 0),
                    "status": "待评估",
                }
                self.db.update_candidate(candidate["id"], updates)
                duplicate_after_dedupe = False
                if self.dedupe_callback:
                    dedupe = self.dedupe_callback([candidate["id"]])
                    duplicate_after_dedupe = bool((dedupe.get("items") or [{}])[0].get("duplicateSkipped"))
                if existing or duplicate_after_dedupe:
                    skipped += 1
                else:
                    saved += 1
            except (TypeError, ValueError):
                failed += 1
        return saved, skipped, failed
