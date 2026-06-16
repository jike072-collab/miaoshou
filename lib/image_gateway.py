"""OpenAI-compatible and custom JSON image relay client."""

import base64
import json
import mimetypes
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from lib.keychain import get_secret


class ImageGatewayError(Exception):
    pass


def _multipart(fields, files):
    boundary = "----MiaoShou%s" % uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.extend((
            ("--%s\r\n" % boundary).encode(),
            ('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode(),
            str(value).encode("utf-8"), b"\r\n",
        ))
    for name, filename, data in files:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.extend((
            ("--%s\r\n" % boundary).encode(),
            ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (name, Path(filename).name)).encode(),
            ("Content-Type: %s\r\n\r\n" % content_type).encode(), data, b"\r\n",
        ))
    chunks.append(("--%s--\r\n" % boundary).encode())
    return b"".join(chunks), "multipart/form-data; boundary=%s" % boundary


def _path_value(payload, path):
    value = payload
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _render_template(value, variables):
    if isinstance(value, dict):
        return {key: _render_template(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_template(item, variables) for item in value]
    if isinstance(value, str):
        for key, replacement in variables.items():
            value = value.replace("{{%s}}" % key, str(replacement))
    return value


def _extract_images(payload, response_path=""):
    values = _path_value(payload, response_path) if response_path else payload.get("data") or payload.get("images") or payload.get("output") or []
    if isinstance(values, (dict, str)):
        values = [values]
    images = []
    for item in values if isinstance(values, list) else []:
        if isinstance(item, str):
            images.append(("url", item))
        elif isinstance(item, dict):
            if item.get("b64_json"):
                images.append(("bytes", base64.b64decode(item["b64_json"])))
            elif item.get("url"):
                images.append(("url", item["url"]))
    return images


def _json_request(url, headers, timeout, method="GET", body=None):
    req = Request(url, data=body, headers=headers, method=method)
    opener = build_opener(ProxyHandler({})) if url.startswith(("http://127.0.0.1", "http://localhost")) else None
    try:
        response = opener.open(req, timeout=timeout) if opener else urlopen(req, timeout=timeout)
        return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise ImageGatewayError("生图接口返回 HTTP %s：%s" % (exc.code, detail))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ImageGatewayError("生图接口调用失败：%s" % exc)


def generate(settings, prompt, source_bytes, source_name="reference.jpg"):
    base_url = str(settings.get("image.base_url") or "").rstrip("/")
    if not base_url:
        raise ImageGatewayError("请先在设置中填写图片中转站 Base URL")
    path = str(settings.get("image.path") or "/v1/images/edits")
    url = base_url + (path if path.startswith("/") else "/" + path)
    model = settings.get("image.model") or "gpt-image-1"
    protocol = settings.get("image.protocol") or "openai"
    timeout = int(settings.get("image.timeout") or 120)
    api_key = get_secret()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key

    if protocol == "openai":
        body, content_type = _multipart(
            {"model": model, "prompt": prompt, "size": "1024x1024", "n": 1},
            [("image", source_name, source_bytes)],
        )
        headers["Content-Type"] = content_type
    else:
        template = settings.get("image.request_template") or {
            "model": "{{model}}", "prompt": "{{prompt}}", "image": "data:image/jpeg;base64,{{image_base64}}",
        }
        if isinstance(template, str):
            try:
                template = json.loads(template)
            except json.JSONDecodeError as exc:
                raise ImageGatewayError("自定义请求模板不是有效JSON：%s" % exc)
        body = json.dumps(_render_template(template, {
            "model": model, "prompt": prompt, "image_base64": base64.b64encode(source_bytes).decode(),
        }), ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    payload = _json_request(url, headers, timeout, method="POST", body=body)
    response_path = settings.get("image.response_path") or ""
    images = _extract_images(payload, response_path)
    task_id = _path_value(payload, settings.get("image.task_id_path"))
    query_path = str(settings.get("image.query_path") or "")
    if not images and task_id and query_path:
        interval = max(0.2, float(settings.get("image.poll_interval") or 2))
        completed = {item.strip().lower() for item in str(settings.get("image.completed_statuses") or "succeeded,completed,success").split(",")}
        failed = {item.strip().lower() for item in str(settings.get("image.failed_statuses") or "failed,error,cancelled").split(",")}
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(interval)
            task_path = query_path.replace("{{taskId}}", str(task_id))
            task_url = base_url + (task_path if task_path.startswith("/") else "/" + task_path)
            payload = _json_request(task_url, headers, timeout)
            images = _extract_images(payload, response_path)
            if images:
                break
            status = str(_path_value(payload, settings.get("image.status_path") or "status") or "").lower()
            if status in failed:
                raise ImageGatewayError("异步生图任务失败：%s" % status)
            if status in completed:
                break
    if not images:
        raise ImageGatewayError("生图接口没有返回可识别的图片")
    return images
