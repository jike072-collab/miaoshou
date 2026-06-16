"""Local runtime configuration and safety gates for the workbench."""

import json
import secrets
import re
import shutil
from copy import deepcopy
from pathlib import Path


DEFAULT_CONFIG = {
    "mode": "real",
    "dry_run_collect": True,
    "collect_to_box_only": True,
    "no_publish": True,
    "max_items_per_run": 10,
    "max_pages_per_keyword": 2,
    "keywords": ["运动鞋", "透气鞋", "凉鞋", "防滑鞋"],
    "enable_dedupe": True,
    "enable_risk_filter": True,
    "enable_title_clean": True,
    "enable_image_check": True,
    "enable_miaoshou_collect": True,
    "max_retry": 2,
    "chrome_profile_dir": "data/chrome-profile",
    "chrome_debug_port": 9222,
}

LOCAL_DIRS = ("logs", "screenshots", "images", "chrome-profile")
PUBLISH_ACTION_PATTERN = re.compile(
    r"(publish|submit|final\s*publish|confirm\s*publish|发布|上架|提交|最终发布|立即发布|确认发布)",
    re.IGNORECASE,
)


def config_example_path(data_dir):
    return Path(data_dir) / "config.example.json"


def config_path(data_dir):
    return Path(data_dir) / "config.json"


def token_path(data_dir):
    return Path(data_dir) / "workbench.token"


def ensure_local_runtime(data_dir):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in LOCAL_DIRS:
        (data_dir / name).mkdir(parents=True, exist_ok=True)
    example = config_example_path(data_dir)
    if not example.exists():
        write_json(example, DEFAULT_CONFIG)
    config = config_path(data_dir)
    if not config.exists():
        shutil.copyfile(example, config)
    if not token_path(data_dir).exists():
        token_path(data_dir).write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return config


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sanitize_config(values):
    merged = deepcopy(DEFAULT_CONFIG)
    if isinstance(values, dict):
        for key in DEFAULT_CONFIG:
            if key not in values:
                continue
            default = DEFAULT_CONFIG[key]
            value = values[key]
            if isinstance(default, bool):
                merged[key] = bool(value)
            elif isinstance(default, int):
                merged[key] = max(0, int(value or 0))
            elif isinstance(default, list):
                if isinstance(value, list):
                    merged[key] = [str(item).strip() for item in value if str(item).strip()]
                else:
                    merged[key] = [item.strip() for item in str(value or "").split(",") if item.strip()]
            else:
                merged[key] = str(value or "")
    merged["mode"] = "mock" if str(merged.get("mode")).lower() == "mock" else "real"
    merged["max_items_per_run"] = min(max(1, int(merged["max_items_per_run"])), 50)
    merged["max_pages_per_keyword"] = min(max(1, int(merged["max_pages_per_keyword"])), 10)
    merged["max_retry"] = min(max(0, int(merged["max_retry"])), 5)
    return merged


def load_config(data_dir):
    ensure_local_runtime(data_dir)
    try:
        payload = json.loads(config_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    config = sanitize_config(payload)
    if config != payload:
        save_config(data_dir, config)
    return config


def save_config(data_dir, values):
    ensure_local_runtime(data_dir)
    config = sanitize_config(values)
    write_json(config_path(data_dir), config)
    return config


def load_or_create_token(data_dir):
    ensure_local_runtime(data_dir)
    path = token_path(data_dir)
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        path.write_text(token, encoding="utf-8")
    return token


def config_status(config):
    return {
        "mode": config["mode"],
        "dryRunCollect": bool(config["dry_run_collect"]),
        "collectToBoxOnly": bool(config.get("collect_to_box_only", False)),
        "noPublish": bool(config["no_publish"]),
        "maxItemsPerRun": int(config["max_items_per_run"]),
        "maxPagesPerKeyword": int(config["max_pages_per_keyword"]),
        "allowCollect": bool(config["enable_miaoshou_collect"]) and (bool(config["dry_run_collect"]) or bool(config.get("collect_to_box_only", False))),
        "publishForbidden": bool(config["no_publish"]),
        "safety": "no_publish" if config["no_publish"] else "publish_allowed",
        "chromeProfileDir": config["chrome_profile_dir"],
        "chromeDebugPort": int(config["chrome_debug_port"]),
    }


def action_text(action):
    if not isinstance(action, dict):
        return str(action or "")
    values = [
        action.get("type", ""),
        action.get("label", ""),
        action.get("text", ""),
        action.get("value", ""),
        " ".join(str(item) for item in action.get("texts", []) if item),
    ]
    selector = action.get("selector", "")
    if selector:
        values.append(selector)
    return " ".join(str(item) for item in values if item)


def contains_publish_action(recipe):
    return any(PUBLISH_ACTION_PATTERN.search(action_text(action)) for action in (recipe or []))


def assert_publish_allowed(config, recipe=None, context=""):
    if not config.get("no_publish", True):
        return True
    if recipe is None or contains_publish_action(recipe):
        label = context or "发布动作"
        raise RuntimeError("%s 已被 no_publish=true 安全开关拦截" % label)
    return True


def contains_publish_text(text):
    return bool(PUBLISH_ACTION_PATTERN.search(str(text or "")))


def assert_safe_collection_action(config, action_text, context="采集动作"):
    if not config.get("no_publish", True):
        raise RuntimeError("%s 需要 no_publish=true 安全开关" % (context or "采集动作"))
    if contains_publish_text(action_text):
        raise RuntimeError("%s 包含危险发布动作，已被 no_publish=true 安全开关拦截" % (context or "采集动作"))
    return True
