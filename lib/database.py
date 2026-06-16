"""SQLite persistence for candidates, products, assets and automation runs."""

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path


MARKETS = ("MY", "PH", "SG", "TH", "VN")


def source_product_id_from_url(url):
    for pattern in (r"offer/(\d+)", r"offerId=(\d+)", r"[?&]id=(\d+)"):
        match = re.search(pattern, url or "")
        if match:
            return match.group(1)
    return ""


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.initialize()

    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self):
        schema = """
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL UNIQUE,
            source_product_id TEXT,
            keyword TEXT,
            title TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            source_price REAL NOT NULL DEFAULT 0,
            min_order INTEGER NOT NULL DEFAULT 0,
            sales_text TEXT NOT NULL DEFAULT '',
            supplier_name TEXT NOT NULL DEFAULT '',
            shop_url TEXT NOT NULL DEFAULT '',
            origin_place TEXT NOT NULL DEFAULT '',
            search_page INTEGER NOT NULL DEFAULT 0,
            search_rank INTEGER NOT NULL DEFAULT 0,
            monthly_sales INTEGER NOT NULL DEFAULT 0,
            repurchase_rate REAL NOT NULL DEFAULT 0,
            rating REAL NOT NULL DEFAULT 0,
            supplier_years REAL NOT NULL DEFAULT 0,
            dispatch_hours REAL NOT NULL DEFAULT 0,
            weight_g REAL NOT NULL DEFAULT 0,
            image_count INTEGER NOT NULL DEFAULT 0,
            sku_complete INTEGER NOT NULL DEFAULT 0,
            risk_flags TEXT NOT NULL DEFAULT '[]',
            images TEXT NOT NULL DEFAULT '[]',
            dedupe_status TEXT NOT NULL DEFAULT 'new_candidate',
            dedupe_reason TEXT NOT NULL DEFAULT '',
            dedupe_reasons TEXT NOT NULL DEFAULT '[]',
            dedupe_checked_at INTEGER,
            precheck_status TEXT NOT NULL DEFAULT '',
            precheck_reason TEXT NOT NULL DEFAULT '',
            precheck_reasons TEXT NOT NULL DEFAULT '[]',
            precheck_details TEXT NOT NULL DEFAULT '{}',
            sea_fit_status TEXT NOT NULL DEFAULT '',
            season_fit_status TEXT NOT NULL DEFAULT '',
            precheck_checked_at INTEGER,
            status TEXT NOT NULL DEFAULT '待评估',
            collection_channel TEXT,
            collected_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sourcing_runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            current_keyword TEXT NOT NULL DEFAULT '',
            current_page INTEGER NOT NULL DEFAULT 0,
            found_count INTEGER NOT NULL DEFAULT 0,
            saved_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            started_at INTEGER NOT NULL,
            finished_at INTEGER,
            error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS collection_box_records (
            id TEXT PRIMARY KEY,
            candidate_id TEXT,
            offer_id TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            clean_title TEXT NOT NULL DEFAULT '',
            image_status TEXT NOT NULL DEFAULT '',
            collected_at INTEGER NOT NULL,
            miaoshou_status TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            market TEXT NOT NULL,
            demand_score REAL NOT NULL,
            sales_score REAL NOT NULL,
            profit_score REAL NOT NULL,
            competition_score REAL NOT NULL,
            logistics_score REAL NOT NULL,
            supply_score REAL NOT NULL,
            media_score REAL NOT NULL,
            total_score REAL NOT NULL,
            confidence REAL NOT NULL,
            hard_blocks TEXT NOT NULL DEFAULT '[]',
            reasons TEXT NOT NULL DEFAULT '[]',
            metrics TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            UNIQUE(candidate_id, market),
            FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            candidate_id TEXT,
            source_url TEXT NOT NULL DEFAULT '',
            source_product_id TEXT,
            title TEXT NOT NULL DEFAULT '',
            sku TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'TikTok采集箱待优化',
            source_price REAL NOT NULL DEFAULT 0,
            cost_price REAL NOT NULL DEFAULT 0,
            sale_price REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'CNY',
            weight_g REAL NOT NULL DEFAULT 0,
            length_cm REAL NOT NULL DEFAULT 0,
            width_cm REAL NOT NULL DEFAULT 0,
            height_cm REAL NOT NULL DEFAULT 0,
            images TEXT NOT NULL DEFAULT '[]',
            main_image TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS market_versions (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            market TEXT NOT NULL,
            language TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL,
            sale_price REAL NOT NULL DEFAULT 0,
            warehouse TEXT NOT NULL DEFAULT '',
            inventory INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0,
            block_reasons TEXT NOT NULL DEFAULT '[]',
            UNIQUE(product_id, market),
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS shops (
            id TEXT PRIMARY KEY,
            account_name TEXT NOT NULL,
            entity_name TEXT NOT NULL DEFAULT '',
            shop_name TEXT NOT NULL,
            market TEXT NOT NULL,
            warehouse TEXT NOT NULL DEFAULT '',
            default_inventory INTEGER NOT NULL DEFAULT 20,
            price_multiplier REAL NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            UNIQUE(account_name, shop_name)
        );
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            url TEXT NOT NULL,
            kind TEXT NOT NULL,
            market TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'pending',
            rejection_reason TEXT NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS generation_jobs (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            preset TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_count INTEGER NOT NULL,
            completed_count INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '{}',
            attempts INTEGER NOT NULL DEFAULT 0,
            failed_api TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            last_prompt TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            last_run_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 1,
            product_ids TEXT NOT NULL,
            shop_ids TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '{}',
            confirmed_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS automation_runs (
            id TEXT PRIMARY KEY,
            batch_id TEXT,
            candidate_id TEXT,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            current_step TEXT NOT NULL DEFAULT '',
            steps TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT '',
            screenshot TEXT NOT NULL DEFAULT '',
            diagnostics TEXT NOT NULL DEFAULT '{}',
            attempts INTEGER NOT NULL DEFAULT 0,
            resolution TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS publish_keys (
            idempotency_key TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            status TEXT NOT NULL,
            product_id TEXT NOT NULL DEFAULT '',
            shop_id TEXT NOT NULL DEFAULT '',
            market TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            failure_reason TEXT NOT NULL DEFAULT '',
            published_at INTEGER,
            created_at INTEGER NOT NULL
        );
        """
        with self.lock, self.connect() as connection:
            connection.executescript(schema)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(automation_runs)")}
            candidate_columns = {row[1] for row in connection.execute("PRAGMA table_info(candidates)")}
            for name, definition in (
                ("min_order", "INTEGER NOT NULL DEFAULT 0"),
                ("sales_text", "TEXT NOT NULL DEFAULT ''"),
                ("supplier_name", "TEXT NOT NULL DEFAULT ''"),
                ("shop_url", "TEXT NOT NULL DEFAULT ''"),
                ("origin_place", "TEXT NOT NULL DEFAULT ''"),
                ("search_page", "INTEGER NOT NULL DEFAULT 0"),
                ("search_rank", "INTEGER NOT NULL DEFAULT 0"),
                ("dedupe_status", "TEXT NOT NULL DEFAULT 'new_candidate'"),
                ("dedupe_reason", "TEXT NOT NULL DEFAULT ''"),
                ("dedupe_reasons", "TEXT NOT NULL DEFAULT '[]'"),
                ("dedupe_checked_at", "INTEGER"),
                ("precheck_status", "TEXT NOT NULL DEFAULT ''"),
                ("precheck_reason", "TEXT NOT NULL DEFAULT ''"),
                ("precheck_reasons", "TEXT NOT NULL DEFAULT '[]'"),
                ("precheck_details", "TEXT NOT NULL DEFAULT '{}'"),
                ("sea_fit_status", "TEXT NOT NULL DEFAULT ''"),
                ("season_fit_status", "TEXT NOT NULL DEFAULT ''"),
                ("precheck_checked_at", "INTEGER"),
            ):
                if name not in candidate_columns:
                    connection.execute("ALTER TABLE candidates ADD COLUMN %s %s" % (name, definition))
            if "context" not in columns:
                connection.execute("ALTER TABLE automation_runs ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")
            if "diagnostics" not in columns:
                connection.execute("ALTER TABLE automation_runs ADD COLUMN diagnostics TEXT NOT NULL DEFAULT '{}'")
            if "resolution" not in columns:
                connection.execute("ALTER TABLE automation_runs ADD COLUMN resolution TEXT NOT NULL DEFAULT ''")
            generation_columns = {row[1] for row in connection.execute("PRAGMA table_info(generation_jobs)")}
            if "context" not in generation_columns:
                connection.execute("ALTER TABLE generation_jobs ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")
            for name, definition in (
                ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("failed_api", "TEXT NOT NULL DEFAULT ''"),
                ("model", "TEXT NOT NULL DEFAULT ''"),
                ("last_prompt", "TEXT NOT NULL DEFAULT ''"),
                ("last_error", "TEXT NOT NULL DEFAULT ''"),
                ("last_run_at", "INTEGER"),
            ):
                if name not in generation_columns:
                    connection.execute("ALTER TABLE generation_jobs ADD COLUMN %s %s" % (name, definition))
            asset_columns = {row[1] for row in connection.execute("PRAGMA table_info(assets)")}
            if "review_status" not in asset_columns:
                connection.execute("ALTER TABLE assets ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
                connection.execute("UPDATE assets SET review_status='approved' WHERE approved=1")
            if "rejection_reason" not in asset_columns:
                connection.execute("ALTER TABLE assets ADD COLUMN rejection_reason TEXT NOT NULL DEFAULT ''")
            publish_columns = {row[1] for row in connection.execute("PRAGMA table_info(publish_keys)")}
            for name, definition in (
                ("product_id", "TEXT NOT NULL DEFAULT ''"),
                ("shop_id", "TEXT NOT NULL DEFAULT ''"),
                ("market", "TEXT NOT NULL DEFAULT ''"),
                ("result", "TEXT NOT NULL DEFAULT ''"),
                ("failure_reason", "TEXT NOT NULL DEFAULT ''"),
                ("published_at", "INTEGER"),
            ):
                if name not in publish_columns:
                    connection.execute("ALTER TABLE publish_keys ADD COLUMN %s %s" % (name, definition))
            self._seed_settings(connection)

    def _seed_settings(self, connection):
        defaults = {
            "evaluation.threshold": 70,
            "evaluation.min_confidence": 70,
            "evaluation.min_margin": 20,
            "automation.mode": "dry_run",
            "automation.chrome_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "automation.cdp_port": 9222,
            "automation.miaoshou_url": "https://erp.91miaoshou.com/",
            "automation.alibaba_url": "https://www.1688.com/",
            "automation.plugin_unpack_dir": "",
            "automation.node_path": "/Users/mac/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
            "automation.plugin_collect_texts": ["采集此产品", "妙手采集", "采集"],
            "automation.plugin_success_texts": ["采集成功", "已采集", "提交成功"],
            "automation.collection_recipe": [],
            "automation.link_collection_recipe": [],
            "automation.publish_recipe": [],
            "image.protocol": "openai",
            "image.base_url": "",
            "image.path": "/v1/images/edits",
            "image.model": "gpt-image-1",
            "image.timeout": 120,
            "image.retries": 2,
            "image.concurrency": 2,
            "image.request_template": {"model": "{{model}}", "prompt": "{{prompt}}", "image": "data:image/jpeg;base64,{{image_base64}}"},
            "image.response_path": "",
            "image.task_id_path": "",
            "image.query_path": "",
            "image.status_path": "status",
            "image.completed_statuses": "succeeded,completed,success",
            "image.failed_statuses": "failed,error,cancelled",
            "image.poll_interval": 2,
            "text.path": "/v1/chat/completions",
            "text.model": "gpt-4.1-mini",
            "market.MY.exchange": 0.65,
            "market.PH.exchange": 7.8,
            "market.SG.exchange": 0.19,
            "market.TH.exchange": 4.9,
            "market.VN.exchange": 3500,
            "market.MY.shipping_cny": 18,
            "market.PH.shipping_cny": 22,
            "market.SG.shipping_cny": 25,
            "market.TH.shipping_cny": 21,
            "market.VN.shipping_cny": 20,
            "market.platform_fee_pct": 12,
            "market.target_margin_pct": 25,
        }
        for key, value in defaults.items():
            connection.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        item = dict(row)
        for key in ("risk_flags", "images", "dedupe_reasons", "precheck_reasons", "precheck_details", "hard_blocks", "reasons", "metrics", "product_ids", "shop_ids", "summary", "steps", "block_reasons", "context", "diagnostics"):
            if key in item and isinstance(item[key], str):
                try:
                    item[key] = json.loads(item[key])
                except json.JSONDecodeError:
                    pass
        for key in ("sku_complete", "blocked", "approved", "enabled", "dry_run"):
            if key in item:
                item[key] = bool(item[key])
        if item.get("approved") and item.get("review_status") in ("", "pending", None):
            item["review_status"] = "approved"
        return item

    def rows(self, sql, params=()):
        with self.lock, self.connect() as connection:
            return [self._decode(row) for row in connection.execute(sql, params).fetchall()]

    def row(self, sql, params=()):
        with self.lock, self.connect() as connection:
            return self._decode(connection.execute(sql, params).fetchone())

    def execute(self, sql, params=()):
        with self.lock, self.connect() as connection:
            cursor = connection.execute(sql, params)
            return cursor.rowcount

    def setting(self, key, default=None):
        row = self.row("SELECT value FROM settings WHERE key = ?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def settings(self):
        result = {}
        for row in self.rows("SELECT key, value FROM settings ORDER BY key"):
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = row["value"]
        return result

    def set_settings(self, values):
        with self.lock, self.connect() as connection:
            for key, value in values.items():
                connection.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )

    def import_candidates(self, urls, keyword=""):
        now = int(time.time())
        created = []
        with self.lock, self.connect() as connection:
            for url in urls:
                candidate_id = uuid.uuid4().hex
                try:
                    connection.execute(
                        "INSERT INTO candidates(id, source_url, source_product_id, keyword, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (candidate_id, url, source_product_id_from_url(url), keyword, now, now),
                    )
                    created.append(candidate_id)
                except sqlite3.IntegrityError:
                    row = connection.execute("SELECT id FROM candidates WHERE source_url = ?", (url,)).fetchone()
                    if row:
                        created.append(row["id"])
        return [self.get_candidate(item_id) for item_id in created]

    def get_candidate(self, candidate_id):
        candidate = self.row("SELECT * FROM candidates WHERE id = ?", (candidate_id,))
        if candidate:
            candidate["evaluations"] = self.rows(
                "SELECT * FROM evaluations WHERE candidate_id = ? ORDER BY market", (candidate_id,)
            )
        return candidate

    def list_candidates(self):
        items = self.rows("SELECT * FROM candidates ORDER BY created_at DESC")
        evaluations = self.rows("SELECT * FROM evaluations ORDER BY market")
        by_candidate = {}
        for item in evaluations:
            by_candidate.setdefault(item["candidate_id"], []).append(item)
        for item in items:
            item["evaluations"] = by_candidate.get(item["id"], [])
        return items

    def update_candidate(self, candidate_id, values):
        allowed = {
            "source_product_id", "keyword", "title", "category", "source_price",
            "min_order", "sales_text", "supplier_name", "shop_url", "origin_place",
            "search_page", "search_rank",
            "monthly_sales", "repurchase_rate", "rating", "supplier_years",
            "dispatch_hours", "weight_g", "image_count", "sku_complete",
            "risk_flags", "images", "dedupe_status", "dedupe_reason", "dedupe_reasons",
            "dedupe_checked_at", "status", "collection_channel", "collected_at",
            "precheck_status", "precheck_reason", "precheck_reasons", "precheck_details",
            "sea_fit_status", "season_fit_status", "precheck_checked_at",
        }
        columns = []
        params = []
        for key, value in values.items():
            if key not in allowed:
                continue
            if key in ("risk_flags", "images", "dedupe_reasons", "precheck_reasons"):
                value = json.dumps(value or [], ensure_ascii=False)
            if key == "precheck_details":
                value = json.dumps(value or {}, ensure_ascii=False)
            if key == "sku_complete":
                value = int(bool(value))
            columns.append("%s = ?" % key)
            params.append(value)
        if not columns:
            return self.get_candidate(candidate_id)
        columns.append("updated_at = ?")
        params.extend((int(time.time()), candidate_id))
        self.execute("UPDATE candidates SET %s WHERE id = ?" % ", ".join(columns), params)
        return self.get_candidate(candidate_id)

    def save_evaluations(self, candidate_id, evaluations):
        with self.lock, self.connect() as connection:
            for item in evaluations:
                connection.execute(
                    """INSERT INTO evaluations(
                        id, candidate_id, market, demand_score, sales_score, profit_score,
                        competition_score, logistics_score, supply_score, media_score,
                        total_score, confidence, hard_blocks, reasons, metrics, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(candidate_id, market) DO UPDATE SET
                        demand_score=excluded.demand_score, sales_score=excluded.sales_score,
                        profit_score=excluded.profit_score, competition_score=excluded.competition_score,
                        logistics_score=excluded.logistics_score, supply_score=excluded.supply_score,
                        media_score=excluded.media_score, total_score=excluded.total_score,
                        confidence=excluded.confidence, hard_blocks=excluded.hard_blocks,
                        reasons=excluded.reasons, metrics=excluded.metrics, created_at=excluded.created_at""",
                    (
                        uuid.uuid4().hex, candidate_id, item["market"], item["demand_score"],
                        item["sales_score"], item["profit_score"], item["competition_score"],
                        item["logistics_score"], item["supply_score"], item["media_score"],
                        item["total_score"], item["confidence"],
                        json.dumps(item["hard_blocks"], ensure_ascii=False),
                        json.dumps(item["reasons"], ensure_ascii=False),
                        json.dumps(item["metrics"], ensure_ascii=False), int(time.time()),
                    ),
                )

    def migrate_products_json(self, path):
        path = Path(path)
        if not path.exists() or self.row("SELECT id FROM products LIMIT 1"):
            return 0
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        count = 0
        for item in items if isinstance(items, list) else []:
            self.save_product(item)
            count += 1
        return count

    def save_product(self, item):
        now = int(time.time())
        product_id = str(item.get("id") or uuid.uuid4().hex)
        values = (
            product_id, item.get("candidateId"), item.get("sourceUrl", ""), item.get("sourceProductId"),
            item.get("title", ""), item.get("sku", ""), item.get("category", ""),
            item.get("status", "TikTok采集箱待优化"), float(item.get("sourcePrice") or 0),
            float(item.get("costPrice") or 0), float(item.get("salePrice") or 0),
            item.get("currency", "CNY"), float(item.get("weightG") or 0),
            float(item.get("lengthCm") or 0), float(item.get("widthCm") or 0),
            float(item.get("heightCm") or 0), json.dumps(item.get("images") or [], ensure_ascii=False),
            item.get("mainImage", ""), item.get("notes", ""), item.get("createdAt") or now, now,
        )
        with self.lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET candidate_id=excluded.candidate_id,
                source_url=excluded.source_url, source_product_id=excluded.source_product_id,
                title=excluded.title, sku=excluded.sku, category=excluded.category,
                status=excluded.status, source_price=excluded.source_price, cost_price=excluded.cost_price,
                sale_price=excluded.sale_price, currency=excluded.currency, weight_g=excluded.weight_g,
                length_cm=excluded.length_cm, width_cm=excluded.width_cm, height_cm=excluded.height_cm,
                images=excluded.images, main_image=excluded.main_image, notes=excluded.notes,
                updated_at=excluded.updated_at""", values,
            )
        return self.get_product(product_id)

    def _product_api(self, item):
        if not item:
            return item
        mapping = {
            "candidate_id": "candidateId", "source_url": "sourceUrl",
            "source_product_id": "sourceProductId", "source_price": "sourcePrice",
            "cost_price": "costPrice", "sale_price": "salePrice", "weight_g": "weightG",
            "length_cm": "lengthCm", "width_cm": "widthCm", "height_cm": "heightCm",
            "main_image": "mainImage", "created_at": "createdAt", "updated_at": "updatedAt",
        }
        return {mapping.get(key, key): value for key, value in item.items()}

    def get_product(self, product_id):
        return self._product_api(self.row("SELECT * FROM products WHERE id = ?", (product_id,)))

    def list_products(self):
        return [self._product_api(item) for item in self.rows("SELECT * FROM products ORDER BY updated_at DESC")]

    def market_versions(self, product_id):
        return self.rows("SELECT * FROM market_versions WHERE product_id=? ORDER BY market", (product_id,))

    def save_market_version(self, product_id, market, values):
        current = self.row("SELECT * FROM market_versions WHERE product_id=? AND market=?", (product_id, market))
        if not current:
            return None
        if current.get("block_reasons"):
            values = {**values, "blocked": True, "block_reasons": current["block_reasons"]}
        allowed = {"title", "description", "sale_price", "warehouse", "inventory", "blocked", "block_reasons"}
        columns, params = [], []
        for key, value in values.items():
            if key not in allowed:
                continue
            if key == "block_reasons":
                value = json.dumps(value or [], ensure_ascii=False)
            if key == "blocked":
                value = int(bool(value))
            columns.append("%s=?" % key)
            params.append(value)
        if columns:
            params.extend((product_id, market))
            self.execute("UPDATE market_versions SET %s WHERE product_id=? AND market=?" % ",".join(columns), params)
        return self.row("SELECT * FROM market_versions WHERE product_id=? AND market=?", (product_id, market))

    def delete_product(self, product_id):
        return self.execute("DELETE FROM products WHERE id = ?", (product_id,))

    def delete_candidate(self, candidate_id):
        return self.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,))

    def create_sourcing_run(self):
        run_id = uuid.uuid4().hex
        now = int(time.time())
        self.execute(
            """INSERT INTO sourcing_runs(
                run_id,status,current_keyword,current_page,found_count,saved_count,
                skipped_count,failed_count,started_at,error
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_id, "idle", "", 0, 0, 0, 0, 0, now, ""),
        )
        return self.get_sourcing_run(run_id)

    def update_sourcing_run(self, run_id, **values):
        allowed = {
            "status", "current_keyword", "current_page", "found_count",
            "saved_count", "skipped_count", "failed_count", "finished_at", "error",
        }
        columns, params = [], []
        for key, value in values.items():
            if key not in allowed:
                continue
            columns.append("%s = ?" % key)
            params.append(value)
        if not columns:
            return self.get_sourcing_run(run_id)
        params.append(run_id)
        self.execute("UPDATE sourcing_runs SET %s WHERE run_id = ?" % ", ".join(columns), params)
        return self.get_sourcing_run(run_id)

    def get_sourcing_run(self, run_id):
        return self.row("SELECT * FROM sourcing_runs WHERE run_id = ?", (run_id,))

    def latest_sourcing_run(self):
        return self.row("SELECT * FROM sourcing_runs ORDER BY started_at DESC LIMIT 1")

    def save_collection_box_record(self, values):
        now = int(time.time())
        record_id = str(values.get("id") or uuid.uuid4().hex)
        payload = (
            record_id,
            values.get("candidate_id") or values.get("candidateId") or "",
            values.get("offer_id") or values.get("offerId") or values.get("source_product_id") or "",
            values.get("source_url") or values.get("sourceUrl") or "",
            values.get("clean_title") or values.get("cleanTitle") or "",
            values.get("image_status") or values.get("imageStatus") or "",
            int(values.get("collected_at") or values.get("collectedAt") or now),
            values.get("miaoshou_status") or values.get("miaoshouStatus") or "",
            values.get("run_id") or values.get("runId") or "",
            now,
        )
        with self.lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO collection_box_records(
                    id,candidate_id,offer_id,source_url,clean_title,image_status,
                    collected_at,miaoshou_status,run_id,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    candidate_id=excluded.candidate_id,
                    offer_id=excluded.offer_id,
                    source_url=excluded.source_url,
                    clean_title=excluded.clean_title,
                    image_status=excluded.image_status,
                    collected_at=excluded.collected_at,
                    miaoshou_status=excluded.miaoshou_status,
                    run_id=excluded.run_id""",
                payload,
            )
        return self.row("SELECT * FROM collection_box_records WHERE id=?", (record_id,))

    def list_collection_box_records(self):
        return self.rows("SELECT * FROM collection_box_records ORDER BY collected_at DESC, created_at DESC")

    def create_run(self, kind, steps, batch_id=None, candidate_id=None, status="queued", context=None):
        run_id = uuid.uuid4().hex
        now = int(time.time())
        self.execute(
            "INSERT INTO automation_runs(id,batch_id,candidate_id,kind,status,steps,diagnostics,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, batch_id, candidate_id, kind, status, json.dumps(steps, ensure_ascii=False), json.dumps({}, ensure_ascii=False), json.dumps(context or {}, ensure_ascii=False), now, now),
        )
        return self.get_run(run_id)

    def update_run(self, run_id, **values):
        allowed = {"status", "current_step", "steps", "error", "screenshot", "diagnostics", "attempts", "resolution", "context"}
        columns, params = [], []
        for key, value in values.items():
            if key in allowed:
                if key in ("steps", "context", "diagnostics"):
                    value = json.dumps(value, ensure_ascii=False)
                columns.append("%s = ?" % key)
                params.append(value)
        columns.append("updated_at = ?")
        params.extend((int(time.time()), run_id))
        self.execute("UPDATE automation_runs SET %s WHERE id = ?" % ", ".join(columns), params)
        return self.get_run(run_id)

    def get_run(self, run_id):
        return self.row("SELECT * FROM automation_runs WHERE id = ?", (run_id,))

    def list_runs(self):
        return self.rows("SELECT * FROM automation_runs ORDER BY created_at DESC LIMIT 100")
