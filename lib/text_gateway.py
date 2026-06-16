"""OpenAI-compatible text localization through the configured relay."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lib.keychain import get_secret


class TextGatewayError(Exception):
    pass


def parse_localization(content):
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TextGatewayError("本地化接口未返回有效JSON：%s" % exc)
    for language in ("en", "th", "vi"):
        if not isinstance(payload.get(language), dict) or not payload[language].get("title"):
            raise TextGatewayError("本地化结果缺少 %s 标题" % language)
        payload[language].setdefault("description", "")
    return payload


def localize(settings, title, description, category):
    base_url = str(settings.get("image.base_url") or "").rstrip("/")
    if not base_url:
        raise TextGatewayError("请先配置中转站 Base URL")
    path = str(settings.get("text.path") or "/v1/chat/completions")
    url = base_url + (path if path.startswith("/") else "/" + path)
    api_key = get_secret()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    prompt = """You are a TikTok Shop Southeast Asia ecommerce localization specialist.
Translate and localize the supplied sports/outdoor product into English, Thai and Vietnamese.
Preserve all factual product details. Do not add brands, certifications, functions, materials or claims not present in the source.
Use natural searchable ecommerce wording. Return JSON only with exactly this shape:
{"en":{"title":"","description":""},"th":{"title":"","description":""},"vi":{"title":"","description":""}}
Category: %s
Source title: %s
Source description: %s""" % (category, title, description or "")
    body = json.dumps({
        "model": settings.get("text.model") or "gpt-4.1-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    try:
        response = urlopen(Request(url, data=body, headers=headers, method="POST"), timeout=int(settings.get("image.timeout") or 120))
        payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
    except HTTPError as exc:
        raise TextGatewayError("本地化接口返回 HTTP %s：%s" % (exc.code, exc.read(600).decode(errors="replace")))
    except (URLError, TimeoutError, OSError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise TextGatewayError("本地化接口调用失败：%s" % exc)
    return parse_localization(content)
