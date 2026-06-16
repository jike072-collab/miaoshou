"""Public product page metadata collector using only Python's standard library."""

import ipaddress
import json
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_REMOTE_SUFFIXES = (".1688.com", ".alicdn.com", ".alibaba.com")


class CollectError(Exception):
    """A user-facing collection error."""


def _validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise CollectError("请输入完整的 http:// 或 https:// 商品链接")
    if parsed.username or parsed.password:
        raise CollectError("链接不能包含用户名或密码")
    hostname = parsed.hostname.lower()
    if hostname == "1688.com" or any(hostname.endswith(suffix) for suffix in ALLOWED_REMOTE_SUFFIXES):
        return parsed
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise CollectError("无法解析该链接的域名")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise CollectError("为保护本机安全，不能采集内网或本机地址")
    return parsed


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_public_url(url, max_bytes, accept):
    _validate_public_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    opener = build_opener(SafeRedirectHandler())
    try:
        response = opener.open(request, timeout=15)
        final_url = response.geturl()
        _validate_public_url(final_url)
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise CollectError("远程内容过大，已停止下载")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise CollectError("远程内容过大，已停止下载")
        return data, response.headers, final_url
    except CollectError:
        raise
    except HTTPError as exc:
        raise CollectError("采集失败：目标网站返回 HTTP %s" % exc.code)
    except (URLError, TimeoutError, OSError):
        raise CollectError("采集失败：目标网站无法访问或响应超时")


class ProductHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = []
        self.json_ld = []
        self.title_parts = []
        self.in_title = False
        self.in_json_ld = False
        self.json_ld_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): value for key, value in attrs if key}
        if tag.lower() == "meta":
            self.meta.append(attrs)
        elif tag.lower() == "title":
            self.in_title = True
        elif tag.lower() == "script" and "ld+json" in (attrs.get("type") or "").lower():
            self.in_json_ld = True
            self.json_ld_parts = []

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False
        elif tag.lower() == "script" and self.in_json_ld:
            self.in_json_ld = False
            text = "".join(self.json_ld_parts).strip()
            if text:
                self.json_ld.append(text)
            self.json_ld_parts = []

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self.in_json_ld:
            self.json_ld_parts.append(data)


def _meta_value(parser, *keys):
    wanted = {key.lower() for key in keys}
    for attrs in parser.meta:
        marker = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if marker in wanted and attrs.get("content"):
            return unescape(attrs["content"]).strip()
    return ""


def _meta_values(parser, *keys):
    wanted = {key.lower() for key in keys}
    values = []
    for attrs in parser.meta:
        marker = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        value = unescape(attrs.get("content") or "").strip()
        if marker in wanted and value and value not in values:
            values.append(value)
    return values


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


def _product_json_ld(parser):
    candidates = []
    for raw in parser.json_ld:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _walk_json(parsed):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(value).lower() == "product" for value in types):
                candidates.append(item)
    return candidates[0] if candidates else {}


def _images_from_json(value):
    images = []
    if isinstance(value, str):
        images.append(value)
    elif isinstance(value, list):
        for item in value:
            images.extend(_images_from_json(item))
    elif isinstance(value, dict):
        url = value.get("url") or value.get("contentUrl")
        if url:
            images.append(str(url))
    return images


def _first_offer(product):
    offers = product.get("offers") if isinstance(product, dict) else {}
    if isinstance(offers, list):
        return offers[0] if offers and isinstance(offers[0], dict) else {}
    return offers if isinstance(offers, dict) else {}


def _number(value):
    if value is None:
        return 0
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else 0


def _weight_grams(product):
    value = product.get("weight") or product.get("shippingWeight")
    if isinstance(value, dict):
        amount = _number(value.get("value"))
        unit = str(value.get("unitCode") or value.get("unitText") or "").lower()
    else:
        amount = _number(value)
        unit = str(value or "").lower()
    if not amount:
        return 0
    if "kg" in unit or "kilogram" in unit or "千克" in unit or "公斤" in unit:
        return round(amount * 1000, 2)
    if "lb" in unit or "pound" in unit:
        return round(amount * 453.592, 2)
    return amount


def scrape_product(url):
    data, headers, final_url = _open_public_url(
        url.strip(),
        MAX_HTML_BYTES,
        "text/html,application/xhtml+xml",
    )
    content_type = headers.get_content_type()
    if content_type not in ("text/html", "application/xhtml+xml"):
        raise CollectError("该链接不是可解析的商品网页")
    charset = headers.get_content_charset() or "utf-8"
    try:
        html = data.decode(charset, errors="replace")
    except LookupError:
        html = data.decode("utf-8", errors="replace")

    parser = ProductHTMLParser()
    parser.feed(html)
    product = _product_json_ld(parser)
    offer = _first_offer(product)
    title = (
        str(product.get("name") or "").strip()
        or _meta_value(parser, "og:title", "twitter:title")
        or unescape("".join(parser.title_parts)).strip()
    )
    images = _images_from_json(product.get("image"))
    images.extend(_meta_values(parser, "og:image", "twitter:image", "image"))
    resolved_images = []
    for image in images:
        resolved = urljoin(final_url, str(image).strip())
        if resolved and resolved not in resolved_images:
            resolved_images.append(resolved)

    source_price = (
        _number(offer.get("price"))
        or _number(product.get("price"))
        or _number(_meta_value(parser, "product:price:amount", "price"))
    )
    currency = (
        str(offer.get("priceCurrency") or "").strip()
        or _meta_value(parser, "product:price:currency", "pricecurrency")
        or "CNY"
    )
    parsed = urlparse(final_url)
    return {
        "title": title,
        "sourceUrl": final_url,
        "sourcePlatform": parsed.hostname.removeprefix("www.") if hasattr(str, "removeprefix") else re.sub(r"^www\.", "", parsed.hostname),
        "sku": str(product.get("sku") or product.get("mpn") or product.get("productID") or "").strip(),
        "category": str(product.get("category") or "").strip(),
        "sourcePrice": source_price,
        "costPrice": source_price,
        "salePrice": 0,
        "currency": currency.upper(),
        "weightG": _weight_grams(product),
        "images": resolved_images[:12],
        "mainImage": resolved_images[0] if resolved_images else "",
    }


def fetch_image(url):
    data, headers, _ = _open_public_url(
        url.strip(),
        MAX_IMAGE_BYTES,
        "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    )
    content_type = headers.get_content_type()
    if not content_type.startswith("image/"):
        raise CollectError("目标链接不是图片")
    return data, content_type
