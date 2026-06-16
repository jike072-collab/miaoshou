"""Deterministic five-market product evaluation."""

from lib.database import MARKETS


MARKET_DEFAULTS = {
    "MY": {"currency": "MYR", "rate": 0.65, "shipping": 18, "trend": 58, "competition": 55},
    "PH": {"currency": "PHP", "rate": 7.8, "shipping": 22, "trend": 62, "competition": 52},
    "SG": {"currency": "SGD", "rate": 0.19, "shipping": 25, "trend": 50, "competition": 68},
    "TH": {"currency": "THB", "rate": 4.9, "shipping": 21, "trend": 65, "competition": 60},
    "VN": {"currency": "VND", "rate": 3500, "shipping": 20, "trend": 67, "competition": 57},
}


def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(maximum, float(value)))


def _market_metrics(payload, market):
    supplied = (payload.get("markets") or {}).get(market) or {}
    defaults = MARKET_DEFAULTS[market]
    return {
        "trend": float(supplied.get("trend", defaults["trend"])),
        "sales_signal": float(supplied.get("salesSignal", 50)),
        "competition": float(supplied.get("competition", defaults["competition"])),
        "target_price_cny": float(supplied.get("targetPriceCny", 0)),
        "platform_fee_pct": float(supplied.get("platformFeePct", 12)),
        "shipping_cny": float(supplied.get("shippingCny", defaults["shipping"])),
        "market_data_complete": bool(supplied.get("dataComplete", False)),
    }


def evaluate_candidate(candidate, payload=None, min_margin=20):
    payload = payload or {}
    cost = float(candidate.get("source_price") or payload.get("sourcePrice") or 0)
    weight = float(candidate.get("weight_g") or payload.get("weightG") or 0)
    monthly_sales = float(candidate.get("monthly_sales") or payload.get("monthlySales") or 0)
    repurchase = float(candidate.get("repurchase_rate") or payload.get("repurchaseRate") or 0)
    rating = float(candidate.get("rating") or payload.get("rating") or 0)
    supplier_years = float(candidate.get("supplier_years") or payload.get("supplierYears") or 0)
    dispatch_hours = float(candidate.get("dispatch_hours") or payload.get("dispatchHours") or 0)
    image_count = int(candidate.get("image_count") or payload.get("imageCount") or 0)
    sku_complete = bool(candidate.get("sku_complete") or payload.get("skuComplete"))
    risk_flags = list(candidate.get("risk_flags") or payload.get("riskFlags") or [])
    category = candidate.get("category") or payload.get("category") or ""
    allowed_category = any(key in category for key in ("鞋", "包", "运动套装", "sports shoes", "sports bag", "sportswear"))

    supply_score = clamp(
        min(monthly_sales / 20, 35)
        + min(repurchase * 1.5, 25)
        + min(supplier_years * 4, 20)
        + (10 if rating >= 4.7 else 6 if rating >= 4.4 else 0)
        + (10 if dispatch_hours and dispatch_hours <= 48 else 4 if dispatch_hours <= 72 else 0)
    )
    logistics_score = 30 if weight <= 0 else 85 if weight <= 1000 else 70 if weight <= 2000 else 45 if weight <= 4000 else 15
    media_score = clamp(image_count * 12 + (20 if sku_complete else 0))
    results = []

    for market in MARKETS:
        metrics = _market_metrics(payload, market)
        target_price = metrics["target_price_cny"]
        fee = target_price * metrics["platform_fee_pct"] / 100
        total_cost = cost + metrics["shipping_cny"] + fee
        margin = ((target_price - total_cost) / target_price * 100) if target_price else 0
        profit_score = clamp((margin - min_margin + 20) * 2) if target_price else 35
        competition_score = clamp(100 - metrics["competition"])
        demand_score = clamp(metrics["trend"])
        sales_score = clamp(metrics["sales_signal"])

        total = (
            demand_score * 0.20 + sales_score * 0.15 + profit_score * 0.25
            + competition_score * 0.15 + logistics_score * 0.10
            + supply_score * 0.10 + media_score * 0.05
        )
        hard_blocks = []
        if risk_flags:
            hard_blocks.extend(risk_flags)
        if not category:
            hard_blocks.append("类目未识别")
        elif not allowed_category:
            hard_blocks.append("类目不在首版支持范围")
        if target_price and margin < min_margin:
            hard_blocks.append("预计毛利率低于 %.0f%%" % min_margin)
        if weight > 5000:
            hard_blocks.append("重量超过首版物流上限")
        if not sku_complete:
            hard_blocks.append("颜色或尺码规格不完整")

        known = [bool(cost), bool(weight), bool(monthly_sales), bool(rating), bool(image_count), sku_complete]
        confidence = 25 + sum(known) * 5 + (23 if metrics["market_data_complete"] else 0)
        confidence = clamp(confidence)
        reasons = [
            "90天趋势 %.0f/100" % demand_score,
            "供应稳定度 %.0f/100" % supply_score,
            "物流适配 %.0f/100" % logistics_score,
            "预计毛利率 %.1f%%" % margin if target_price else "尚未配置目标售价，利润分使用保守值",
        ]
        results.append({
            "market": market,
            "demand_score": round(demand_score, 1),
            "sales_score": round(sales_score, 1),
            "profit_score": round(profit_score, 1),
            "competition_score": round(competition_score, 1),
            "logistics_score": round(logistics_score, 1),
            "supply_score": round(supply_score, 1),
            "media_score": round(media_score, 1),
            "total_score": round(total, 1),
            "confidence": round(confidence, 1),
            "hard_blocks": sorted(set(hard_blocks)),
            "reasons": reasons,
            "metrics": {**metrics, "margin_pct": round(margin, 2), "total_cost_cny": round(total_cost, 2)},
        })
    return results


def evaluation_status(results, threshold=70, min_confidence=70):
    qualified = [
        item for item in results
        if item["total_score"] >= threshold and item["confidence"] >= min_confidence and not item["hard_blocks"]
    ]
    if qualified:
        return "已达标"
    if any(item["confidence"] < min_confidence for item in results):
        return "待确认"
    return "未达标"
