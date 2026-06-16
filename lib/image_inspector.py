"""Download and inspect candidate images with lightweight rules."""

import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from lib.collector import CollectError, fetch_image


DEFAULT_MIN_DIMENSION = 500
DEFAULT_MIN_IMAGES = 3
PLATFORM_MARKERS = ("1688", "taobao", "tmall", "pinduoduo", "pdd", "alibaba", "lazada", "shopee")
CONTACT_MARKERS = ("微信", "vx", "v信", "电话", "手机号", "whatsapp", "telegram", "tel", "contact")
WATERMARK_MARKERS = ("watermark", "wm", "logo", "brand", "sample")
QR_MARKERS = ("qrcode", "qr", "二维码")
CHINESE_HINT_MARKERS = ("中文", "汉字", "cn", "chinese")


def _safe_name(url, index):
    parsed = urlparse(url or "")
    tail = Path(parsed.path or "").name or "image"
    tail = re.sub(r"[^A-Za-z0-9._-]+", "_", tail)[:60] or "image"
    return "%s-%s-%s" % (index + 1, uuid.uuid4().hex[:8], tail)


def _image_size_bytes(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big"), "png"
    if raw[:2] in (b"\xff\xd8",):
        index = 2
        while index < len(raw) - 1:
            if raw[index] != 0xFF:
                index += 1
                continue
            marker = raw[index + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if index + 9 < len(raw):
                    height = int.from_bytes(raw[index + 5:index + 7], "big")
                    width = int.from_bytes(raw[index + 7:index + 9], "big")
                    return width, height, "jpeg"
                break
            if marker in (0xD8, 0xD9):
                index += 2
                continue
            if index + 4 >= len(raw):
                break
            segment_length = int.from_bytes(raw[index + 2:index + 4], "big")
            if segment_length <= 0:
                break
            index += 2 + segment_length
        return 0, 0, "jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" and len(raw) >= 30:
        chunk = raw[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(raw[24:27], "little")
            height = 1 + int.from_bytes(raw[27:30], "little")
            return width, height, "webp"
        if chunk == b"VP8L" and len(raw) >= 25 and raw[20] == 0x2F:
            b0, b1, b2, b3 = raw[21], raw[22], raw[23], raw[24]
            width = 1 + (((b1 & 0x3F) << 8) | b0)
            height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
            return width, height, "webp"
        if chunk == b"VP8 " and raw[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(raw[26:28], "little") & 0x3FFF
            height = int.from_bytes(raw[28:30], "little") & 0x3FFF
            return width, height, "webp"
        return 0, 0, "webp"
    return 0, 0, ""


def _text_hits(text, markers):
    text = str(text or "").lower()
    return [marker for marker in markers if marker.lower() in text]


def inspect_image_source(url, raw=None):
    parsed = urlparse(url or "")
    basis = " ".join([url or "", parsed.path or "", Path(parsed.path or "").name or ""])
    platform_hits = _text_hits(basis, PLATFORM_MARKERS)
    contact_hits = _text_hits(basis, CONTACT_MARKERS)
    watermark_hits = _text_hits(basis, WATERMARK_MARKERS)
    qr_hits = _text_hits(basis, QR_MARKERS)
    chinese_hits = _text_hits(basis, CHINESE_HINT_MARKERS)
    width = height = 0
    file_type = ""
    if raw:
        width, height, file_type = _image_size_bytes(raw)
    unknown_size = bool(raw and not (width and height))
    too_small = bool(width and height and (width < DEFAULT_MIN_DIMENSION or height < DEFAULT_MIN_DIMENSION))
    usable = not any((platform_hits, contact_hits, watermark_hits, qr_hits, chinese_hits)) and not too_small
    needs_generation = False
    status = "original_usable"
    reasons = []
    if not raw:
        status = "image_failed"
        reasons.append("图片下载失败")
    elif unknown_size:
        status = "needs_cleanup"
        needs_generation = True
        reasons.append("无法识别图片尺寸")
    elif too_small:
        status = "needs_cleanup"
        needs_generation = True
        reasons.append("图片尺寸过小")
    if platform_hits:
        status = "needs_cleanup"
        needs_generation = True
        reasons.append("存在平台标识")
    if contact_hits:
        status = "needs_cleanup"
        needs_generation = True
        reasons.append("存在联系方式")
    if qr_hits:
        status = "needs_cleanup"
        needs_generation = True
        reasons.append("存在二维码")
    if watermark_hits:
        status = "needs_cleanup"
        needs_generation = True
        reasons.append("存在明显水印")
    if chinese_hits:
        status = "needs_cleanup"
        needs_generation = True
        reasons.append("存在中文文本")
    if not reasons and raw:
        status = "original_usable"
    score = 92 if status == "original_usable" else 55 if status == "needs_cleanup" else 0
    if not raw:
        score = 0
    return {
        "status": status,
        "usable": usable and bool(raw),
        "needs_generation": needs_generation,
        "reasons": reasons,
        "details": {
            "width": width,
            "height": height,
            "fileType": file_type,
            "platformHits": platform_hits,
            "contactHits": contact_hits,
            "watermarkHits": watermark_hits,
            "qrHits": qr_hits,
            "chineseHits": chinese_hits,
            "unknownSize": unknown_size,
            "sizeTooSmall": too_small,
            "ocrAvailable": False,
            "clearScore": score,
            "minimumImages": DEFAULT_MIN_IMAGES,
        },
    }


def save_downloaded_image(path_dir, url, raw, index=0, content_type=""):
    path_dir = Path(path_dir)
    path_dir.mkdir(parents=True, exist_ok=True)
    _width, _height, file_type = _image_size_bytes(raw)
    extension = file_type or ""
    if not extension and "png" in str(content_type).lower():
        extension = "png"
    elif not extension and "webp" in str(content_type).lower():
        extension = "webp"
    elif not extension and "jpeg" in str(content_type).lower():
        extension = "jpg"
    extension = extension or "jpg"
    extension = "jpg" if extension == "jpeg" else extension
    filename = _safe_name(url, index)
    if not filename.lower().endswith("." + extension):
        filename += "." + extension
    path = path_dir / filename
    path.write_bytes(raw)
    return path


def analyze_candidate_images(candidate, images=None, image_dir=None):
    candidate = candidate or {}
    image_dir = Path(image_dir) if image_dir else None
    source_images = []
    for value in images if images is not None else (candidate.get("images") or []):
        if value and value not in source_images:
            source_images.append(str(value))
    if not source_images and candidate.get("main_image_url"):
        source_images.append(str(candidate.get("main_image_url")))
    if not source_images and candidate.get("mainImage"):
        source_images.append(str(candidate.get("mainImage")))
    results = []
    local_paths = []
    reasons = []
    failed = []
    for index, url in enumerate(source_images):
        try:
            raw, content_type = fetch_image(url)
        except CollectError as exc:
            failed.append({"url": url, "error": str(exc)})
            results.append({
                "url": url,
                "localPath": "",
                "downloaded": False,
                "status": "image_failed",
                "reasons": [str(exc)],
                "details": {"error": str(exc)},
            })
            continue
        saved = save_downloaded_image(image_dir, url, raw, index=index, content_type=content_type) if image_dir else None
        local_paths.append(str(saved) if saved else "")
        analysis = inspect_image_source(url, raw)
        if analysis["reasons"]:
            reasons.extend(analysis["reasons"])
        if saved:
            analysis["localPath"] = str(saved)
            analysis["downloaded"] = True
        else:
            analysis["localPath"] = ""
            analysis["downloaded"] = False
        analysis["url"] = url
        results.append(analysis)
    usable_results = [item for item in results if item["status"] == "original_usable"]
    usable_count = len(usable_results)
    minimum_required = DEFAULT_MIN_IMAGES
    if not source_images:
        status = "image_failed"
        final_reasons = ["未找到候选图片"]
    elif failed and not results:
        status = "image_failed"
        final_reasons = ["图片下载失败"]
    elif usable_count >= minimum_required:
        status = "image_ready"
        final_reasons = []
    elif results and all(item["status"] == "image_failed" for item in results):
        status = "image_failed"
        final_reasons = ["图片下载失败"]
    elif any(item["status"] == "needs_cleanup" for item in results):
        status = "needs_generation"
        final_reasons = sorted(set(reasons))
    else:
        status = "needs_generation"
        final_reasons = ["图片数量不足"]
    if status == "image_failed" and not final_reasons:
        final_reasons = ["图片处理失败"]
    summary = {
        "status": status,
        "reasons": final_reasons,
        "details": {
            "totalImages": len(source_images),
            "usableImages": usable_count,
            "failedImages": len(failed),
            "results": results,
            "localPaths": [path for path in local_paths if path],
            "minimumImages": minimum_required,
            "sourceCandidates": source_images,
        },
        "local_paths": [path for path in local_paths if path],
        "failed": failed,
        "items": results,
    }
    return summary


def make_image_record_payload(candidate, summary, image_path=""):
    return {
        "candidate_id": (candidate or {}).get("id") or "",
        "source_url": (candidate or {}).get("source_url") or "",
        "local_path": image_path or "",
        "status": summary.get("status") or "image_pending",
        "reasons": summary.get("reasons") or [],
        "details": summary.get("details") or {},
        "checked_at": int(time.time()),
    }
