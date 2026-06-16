#!/usr/bin/env python3
"""Seed internal workflow demo data for the Miaoshou workbench."""

import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.database import Database  # noqa: E402


def insert_evaluation(db, candidate_id, market, score, confidence=82, hard_blocks=None):
    now = int(time.time())
    db.execute(
        """INSERT INTO evaluations(id,candidate_id,market,demand_score,sales_score,profit_score,competition_score,
        logistics_score,supply_score,media_score,total_score,confidence,hard_blocks,reasons,metrics,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(candidate_id, market) DO UPDATE SET total_score=excluded.total_score,confidence=excluded.confidence,
        hard_blocks=excluded.hard_blocks,reasons=excluded.reasons,metrics=excluded.metrics""",
        (
            uuid.uuid4().hex,
            candidate_id,
            market,
            score,
            score,
            score,
            80,
            80,
            80,
            80,
            score,
            confidence,
            json.dumps(hard_blocks or [], ensure_ascii=False),
            json.dumps(["演示数据"], ensure_ascii=False),
            json.dumps({"target_price_cny": 149, "market_data_complete": True, "margin_pct": 28}, ensure_ascii=False),
            now,
        ),
    )


def main():
    data_dir = Path(os.environ.get("WORKBENCH_DATA_DIR", str(ROOT / "data"))).resolve()
    db = Database(data_dir / "workbench.db")
    asset_dir = data_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    now = int(time.time())

    urls = [
        "https://detail.1688.com/offer/900001.html",
        "https://detail.1688.com/offer/900002.html",
        "https://detail.1688.com/offer/900003.html",
        "https://detail.1688.com/offer/900004.html",
    ]
    candidates = db.import_candidates(urls, keyword="模块9联调")
    need_data, unqualified, qualified, collected = candidates

    db.update_candidate(need_data["id"], {"title": "缺数据运动鞋"})
    db.update_candidate(unqualified["id"], {
        "title": "未达标运动包", "category": "运动包", "source_price": 80, "weight_g": 700,
        "monthly_sales": 120, "rating": 4.4, "dispatch_hours": 48, "image_count": 2,
        "sku_complete": 1, "images": ["https://example.com/unqualified.jpg"],
    })
    for market in ("MY", "PH", "SG", "TH", "VN"):
        insert_evaluation(db, unqualified["id"], market, 48, confidence=76, hard_blocks=["毛利不足"] if market == "MY" else [])

    db.update_candidate(qualified["id"], {
        "title": "可采集运动套装", "category": "运动套装", "source_price": 55, "weight_g": 500,
        "monthly_sales": 500, "rating": 4.8, "dispatch_hours": 24, "image_count": 3,
        "sku_complete": 1, "images": ["https://example.com/qualified.jpg"],
    })
    for market in ("MY", "PH", "SG", "TH", "VN"):
        insert_evaluation(db, qualified["id"], market, 82)

    db.update_candidate(collected["id"], {
        "title": "已采集轻量运动鞋", "category": "运动鞋", "source_price": 40, "weight_g": 420,
        "monthly_sales": 900, "rating": 4.9, "dispatch_hours": 18, "image_count": 4,
        "sku_complete": 1, "images": ["https://example.com/collected.jpg"], "collected_at": now,
    })
    for market in ("MY", "PH", "SG", "TH", "VN"):
        insert_evaluation(db, collected["id"], market, 86)

    product = db.save_product({
        "candidateId": collected["id"], "sourceUrl": collected["source_url"],
        "sourceProductId": collected.get("source_product_id"), "title": "已采集轻量运动鞋",
        "sku": "DEMO-SHOE-1", "category": "运动鞋", "costPrice": 40, "weightG": 420,
        "images": ["https://example.com/collected.jpg"], "mainImage": "https://example.com/collected.jpg",
        "status": "待图片审核",
    })
    import app  # noqa: E402
    app.DB = db
    app.create_market_versions(product["id"])
    db.save_market_version(product["id"], "MY", {"title": "Light Sport Shoes", "sale_price": 129, "warehouse": "MY-WH", "inventory": 20})

    db.execute(
        "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, product["id"], "/assets/demo-pending.jpg", "generated", 0, "pending", "", "demo", now),
    )
    db.execute(
        "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, product["id"], "/assets/demo-approved.jpg", "uploaded", 1, "approved", "", "demo approved", now),
    )
    shop_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO shops(id,account_name,entity_name,shop_name,market,warehouse,default_inventory,price_multiplier,enabled) VALUES (?,?,?,?,?,?,?,?,?)",
        (shop_id, "demo-account", "demo-entity", "MY Demo Shop", "MY", "MY-WH", 20, 1, 1),
    )
    batch_id = "demo-failed-batch"
    db.execute(
        "INSERT OR REPLACE INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (batch_id, "模块9失败演示批次", "failed", 1, json.dumps([product["id"]]), json.dumps([shop_id]), "{}", now, now),
    )
    db.create_run("publish", ["批次预检", "上传商品"], batch_id=batch_id, status="failed", context={"demo": True})

    print("Seeded workflow demo data in %s" % data_dir)


if __name__ == "__main__":
    main()
