"""Deterministic product title cleaning for TikTok collection drafts."""

import re


SUPPLY_CHAIN_TERMS = (
    "TikTok 爆款",
    "TikTok爆款",
    "一键代发",
    "一件代发",
    "厂家直销",
    "工厂货源",
    "源头厂家",
    "批发价",
    "网红同款",
    "跨境",
    "外贸",
    "代发",
    "1688",
    "阿里巴巴",
    "淘宝",
    "天猫",
    "拼多多",
    "批发",
    "爆款",
    "Shopee",
    "Lazada",
    "亚马逊",
    "速卖通",
)


RISK_MARKETING_TERMS = (
    "100% 有效",
    "100%有效",
    "保证有效",
    "医疗级",
    "正品大牌",
    "最好",
    "第一",
    "治疗",
    "治愈",
    "减肥",
    "瘦身",
    "永久",
    "防癌",
    "抗菌",
    "杀菌",
    "原单",
    "高仿",
    "复刻",
)


TOKEN_MAP = (
    ("男女同款", "Unisex"),
    ("儿童", "Kids"),
    ("男士", "Men"),
    ("女士", "Women"),
    ("女款", "Women"),
    ("男款", "Men"),
    ("夏季", "Summer"),
    ("春夏", "Spring Summer"),
    ("秋冬", "Autumn Winter"),
    ("透气", "Breathable"),
    ("防滑", "Non Slip"),
    ("防水", "Waterproof"),
    ("防潮", "Moisture Resistant"),
    ("轻便", "Lightweight"),
    ("轻量", "Lightweight"),
    ("软底", "Soft Sole"),
    ("厚底", "Thick Sole"),
    ("网面", "Mesh"),
    ("飞织", "Knit"),
    ("皮革", "Leather"),
    ("帆布", "Canvas"),
    ("户外", "Outdoor"),
    ("沙滩", "Beach"),
    ("休闲", "Casual"),
    ("跑步", "Running"),
    ("健身", "Fitness"),
    ("训练", "Training"),
    ("运动", "Sports"),
    ("旅行", "Travel"),
    ("日常", "Everyday"),
    ("凉鞋", "Sandals"),
    ("拖鞋", "Slippers"),
    ("运动鞋", "Sports Shoes"),
    ("跑鞋", "Running Shoes"),
    ("休闲鞋", "Casual Shoes"),
    ("防滑鞋", "Non Slip Shoes"),
    ("沙滩鞋", "Beach Shoes"),
    ("鞋", "Shoes"),
    ("背包", "Backpack"),
    ("运动包", "Sports Bag"),
    ("健身包", "Gym Bag"),
    ("斜挎包", "Crossbody Bag"),
    ("收纳包", "Storage Bag"),
    ("包", "Bag"),
    ("运动套装", "Sports Set"),
    ("瑜伽套装", "Yoga Set"),
    ("短裤", "Shorts"),
    ("上衣", "Top"),
    ("T恤", "T Shirt"),
    ("T恤衫", "T Shirt"),
    ("配饰", "Accessories"),
)


PRODUCT_TOKEN_PRIORITY = (
    "Sports Shoes",
    "Running Shoes",
    "Casual Shoes",
    "Non Slip Shoes",
    "Beach Shoes",
    "Sandals",
    "Slippers",
    "Shoes",
    "Backpack",
    "Sports Bag",
    "Gym Bag",
    "Crossbody Bag",
    "Storage Bag",
    "Bag",
    "Sports Set",
    "Yoga Set",
    "Shorts",
    "Top",
    "T Shirt",
    "Accessories",
)

MODIFIER_PRIORITY = (
    "Breathable",
    "Non Slip",
    "Waterproof",
    "Moisture Resistant",
    "Lightweight",
    "Soft Sole",
    "Thick Sole",
    "Mesh",
    "Knit",
    "Leather",
    "Canvas",
    "Summer",
    "Spring Summer",
    "Autumn Winter",
    "Outdoor",
    "Beach",
    "Casual",
    "Running",
    "Fitness",
    "Training",
    "Sports",
    "Travel",
    "Everyday",
    "Unisex",
    "Men",
    "Women",
    "Kids",
)


def _compile_term(term):
    return re.compile(re.escape(term).replace(r"\ ", r"\s*"), re.IGNORECASE)


def _unique(values):
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _term_matches(text, terms, kind):
    matches = []
    for term in terms:
        for match in _compile_term(term).finditer(text):
            matches.append({
                "start": match.start(),
                "end": match.end(),
                "term": term.replace("TikTok爆款", "TikTok 爆款").replace("100%有效", "100% 有效").replace("一件代发", "一键代发"),
                "kind": kind,
            })
    matches.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))
    accepted = []
    covered = []
    for match in matches:
        span = range(match["start"], match["end"])
        if any(match["start"] < end and match["end"] > start for start, end in covered):
            continue
        accepted.append(match)
        covered.append((span.start, span.stop))
    return accepted


def _remove_terms(text, matches):
    cleaned = text
    for match in sorted(matches, key=lambda item: item["start"], reverse=True):
        cleaned = cleaned[:match["start"]] + " " + cleaned[match["end"]:]
    return cleaned


def _normalize_text(text):
    text = re.sub(r"[【】\[\]（）(){}<>《》\"“”'‘’]", " ", text)
    text = re.sub(r"[|/\\,，.。:：;；!！?？+*~、]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _dedupe_words(text):
    words = []
    seen = set()
    for word in re.split(r"\s+", text.strip()):
        key = word.lower()
        if key and key not in seen:
            words.append(word)
            seen.add(key)
    return " ".join(words)


class TitleCleaner:
    def __init__(self, supply_terms=None, risk_terms=None):
        self.supply_terms = tuple(supply_terms or SUPPLY_CHAIN_TERMS)
        self.risk_terms = tuple(risk_terms or RISK_MARKETING_TERMS)

    def analyze_terms(self, title):
        text = str(title or "")
        supply = _term_matches(text, self.supply_terms, "supply")
        risk = _term_matches(text, self.risk_terms, "risk")
        return {
            "removed_terms": _unique(item["term"] for item in supply),
            "risk_terms": _unique(item["term"] for item in risk),
            "matches": sorted(supply + risk, key=lambda item: item["start"]),
        }

    def has_supply_or_platform_terms(self, title):
        return bool(self.analyze_terms(title)["removed_terms"])

    def clean(self, title):
        original = str(title or "").strip()
        analysis = self.analyze_terms(original)
        stripped = _normalize_text(_remove_terms(original, analysis["matches"]))
        clean_title = self._english_title(stripped)
        if not clean_title:
            clean_title = self._fallback_title(stripped)
        clean_title = _dedupe_words(clean_title)
        clean_title = re.sub(r"\s+", " ", clean_title).strip(" -_/")
        if len(clean_title) > 120:
            clean_title = clean_title[:120].rsplit(" ", 1)[0] or clean_title[:120]
        if not clean_title:
            clean_title = "Unbranded Product"
        return {
            "original_title": original,
            "clean_title": clean_title,
            "removed_terms": analysis["removed_terms"],
            "risk_terms": analysis["risk_terms"],
            "status": "title_cleaned",
        }

    def _english_title(self, text):
        found = []
        for token, english in TOKEN_MAP:
            if token in text:
                found.append(english)
        product = next((item for item in PRODUCT_TOKEN_PRIORITY if item in found), "")
        product_words = {word.lower() for word in product.split()}
        modifiers = [
            item for item in MODIFIER_PRIORITY
            if item in found
            and item != product
            and not ({word.lower() for word in item.split()} <= product_words)
        ]
        ascii_words = re.findall(r"[A-Za-z][A-Za-z0-9%+-]*", text)
        words = []
        for word in ascii_words:
            lowered = word.lower()
            if lowered in {"tiktok", "shopee", "lazada", "amazon", "alibaba", "taobao", "tmall"}:
                continue
            words.append(word[:1].upper() + word[1:])
        return " ".join(modifiers + words + ([product] if product else []))

    def _fallback_title(self, text):
        text = re.sub(r"[\u4e00-\u9fff]", " ", text)
        text = _normalize_text(text)
        if text:
            return text.title()
        return ""
