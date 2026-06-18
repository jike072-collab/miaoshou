"""Local runtime configuration and safety gates for the workbench."""

import json
import os
import platform
import re
import secrets
import shutil
import sys
import time
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse


CONFIG_VERSION = 1
CONFIG_DOC = "docs/module-01/config-model.md"
CONFIG_PRIORITY = (
    "runtime_system",
    "structured_config_json",
    "environment_sensitive_values",
    "legacy_config_json",
    "legacy_settings_mirror",
    "default_config",
)

MAX_KEYWORDS = 20
MAX_TARGET_COUNT = 500
MAX_CANDIDATE_LIMIT = 2000
MAX_SAFE_ITEMS_PER_RUN = 10
MAX_SAFE_PAGES_PER_KEYWORD = 2
MAX_SEARCH_PAGES = 10
MAX_STEP_RETRY = 5
MAX_TASK_FAILURE_LIMIT = 100
MAX_TIMEOUT_SECONDS = 300
MAX_COLLECTION_INTERVAL_SECONDS = 60
MAX_IMAGE_DIMENSION = 10000

IMAGE_STRATEGIES = ("original", "inspect_and_fix", "regenerate")
RUN_MODES = ("simulation", "collect_to_box")
DEDUP_SCOPES = ("local", "history", "all")
SENSITIVE_FIELD_PATTERN = re.compile(r"(api[_-]?key|authorization|token|cookie|password|passwd|secret)", re.IGNORECASE)
LOCKED_TRUE_ADVANCED_FIELDS = (
    "no_publish",
    "collect_to_box_only",
    "safety_checks_enabled",
    "enable_dedupe",
    "enable_risk_filter",
    "enable_title_clean",
)
SAFE_SYSTEM_FIELDS = (
    "platform",
    "python_version",
    "chrome_detected",
    "cdp_available",
    "alibaba_logged_in",
    "miaoshou_logged_in",
    "plugin_detected",
    "last_environment_check_at",
)
LEGACY_RUN_MODE_FIELDS = ("dry_run_collect", "collect_to_box_only", "mode", "real_mode", "live_mode", "publish_enabled")

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "documentation": CONFIG_DOC,
    "user": {
        "category": "鞋类",
        "keywords": ["运动鞋", "透气鞋", "凉鞋", "防滑鞋"],
        "target_count": 50,
        "candidate_limit": 200,
        "purchase_price_min": 0,
        "purchase_price_max": 200,
        "max_weight_kg": 2,
        "minimum_profit_margin": 0.2,
        "auto_season_check": True,
        "image_strategy": "inspect_and_fix",
        "run_mode": "simulation",
    },
    "advanced": {
        "search_max_pages": 2,
        "page_load_timeout_seconds": 30,
        "step_retry_count": 2,
        "task_failure_limit": 10,
        "collection_interval_seconds": 3,
        "prefer_plugin": True,
        "enable_link_fallback": True,
        "browser_path": "",
        "browser_user_data_dir": "data/chrome-profile",
        "cdp_port": 9222,
        "alibaba_url": "https://www.1688.com/",
        "miaoshou_url": "https://erp.91miaoshou.com/",
        "plugin_id": "",
        "database_path": "data/workbench.db",
        "log_path": "data/logs",
        "image_inspection_enabled": True,
        "image_min_width": 600,
        "image_min_height": 600,
        "image_service_url": "",
        "image_service_timeout_seconds": 30,
        "dedup_scope": "all",
        "no_publish": True,
        "collect_to_box_only": True,
        "safety_checks_enabled": True,
        "enable_dedupe": True,
        "enable_risk_filter": True,
        "enable_title_clean": True,
        "enable_image_check": True,
        "enable_miaoshou_collect": True,
        "per_run_item_limit": 10,
        "per_keyword_page_limit": 2,
    },
    "system": {
        "platform": "",
        "python_version": "",
        "chrome_detected": False,
        "chrome_path_detected": "",
        "cdp_available": False,
        "alibaba_logged_in": False,
        "miaoshou_logged_in": False,
        "plugin_detected": False,
        "last_environment_check_at": "",
    },
}

LOCAL_DIRS = ("logs", "screenshots", "images", "chrome-profile")
PUBLISH_ACTION_PATTERN = re.compile(
    r"(publish|submit|final\s*publish|confirm\s*publish|发布|上架|提交|最终发布|立即发布|确认发布)",
    re.IGNORECASE,
)

LEGACY_FIELD_MAPPINGS = {
    "category": ("user.category", "trim string"),
    "keywords": ("user.keywords", "split string or normalize list"),
    "target_count": ("user.target_count", "integer"),
    "max_items_per_run": ("advanced.per_run_item_limit", "integer clamped to safe limit"),
    "candidate_limit": ("user.candidate_limit", "integer"),
    "purchase_price_min": ("user.purchase_price_min", "number CNY"),
    "purchase_price_max": ("user.purchase_price_max", "number CNY"),
    "max_weight_kg": ("user.max_weight_kg", "number kg"),
    "max_weight_g": ("user.max_weight_kg", "grams divided by 1000"),
    "minimum_profit_margin": ("user.minimum_profit_margin", "decimal 0-1"),
    "min_profit_margin": ("user.minimum_profit_margin", "decimal or percent converted to decimal"),
    "market.target_margin_pct": ("user.minimum_profit_margin", "percent divided by 100"),
    "auto_season_check": ("user.auto_season_check", "boolean"),
    "enable_image_check": ("advanced.enable_image_check", "boolean"),
    "image_strategy": ("user.image_strategy", "enum"),
    "dry_run_collect": ("user.run_mode", "true -> simulation"),
    "collect_to_box_only": ("user.run_mode", "true with dry_run false -> collect_to_box"),
    "mode": ("user.run_mode", "mock/dry_run -> simulation; real -> collect_to_box when safe"),
    "real_mode": ("user.run_mode", "ambiguous true -> simulation warning"),
    "live_mode": ("user.run_mode", "ignored, simulation warning"),
    "publish_enabled": ("legacy.flat.publish_enabled", "rejected and warned"),
    "no_publish": ("advanced.no_publish", "must remain true"),
    "chrome_path": ("advanced.browser_path", "path"),
    "automation.chrome_path": ("advanced.browser_path", "path"),
    "chrome_profile_dir": ("advanced.browser_user_data_dir", "path"),
    "automation.chrome_profile_dir": ("advanced.browser_user_data_dir", "path"),
    "chrome_debug_port": ("advanced.cdp_port", "port"),
    "automation.cdp_port": ("advanced.cdp_port", "port"),
    "automation.alibaba_url": ("advanced.alibaba_url", "http(s) URL"),
    "automation.miaoshou_url": ("advanced.miaoshou_url", "http(s) URL"),
    "automation.plugin_extension_id": ("advanced.plugin_id", "string"),
    "max_retry": ("advanced.step_retry_count", "integer"),
    "image.retries": ("advanced.step_retry_count", "integer"),
    "image.timeout": ("advanced.image_service_timeout_seconds", "seconds"),
    "image.base_url": ("advanced.image_service_url", "http(s) URL"),
    "image.request_template": ("legacy.settings.image.request_template", "legacy preserved"),
    "market.*.exchange": ("legacy.settings.market", "legacy preserved"),
    "market.*.shipping_cny": ("legacy.settings.market", "legacy preserved"),
    "evaluation.*": ("legacy.settings.evaluation", "legacy preserved"),
}


class ConfigValidationError(ValueError):
    def __init__(self, message, errors=None, warnings=None):
        super().__init__(message)
        self.errors = errors or []
        self.warnings = warnings or []


def _issue(field, reason, value=None, allowed=None):
    return {"field": field, "reason": reason, "message": reason, "value": value, "allowed": allowed}


def _public_issue(issue):
    if isinstance(issue, dict):
        normalized = dict(issue)
    else:
        normalized = {"field": "config", "reason": str(issue), "value": "", "allowed": ""}
    if "message" not in normalized:
        normalized["message"] = normalized.get("reason") or "配置错误"
    if SENSITIVE_FIELD_PATTERN.search(str(normalized.get("field", ""))):
        normalized["value"] = "***configured***" if normalized.get("value") else ""
    elif isinstance(normalized.get("value"), dict):
        value = deepcopy(normalized["value"])
        _redact_sensitive_mapping(value)
        normalized["value"] = value
    return normalized


def _format_issue(issue):
    allowed = issue.get("allowed")
    suffix = "；允许范围或合法值：%s" % (allowed,) if allowed not in (None, "") else ""
    return "%s：%s；当前值：%r%s" % (
        issue.get("field") or "config",
        issue.get("reason") or "配置错误",
        issue.get("value"),
        suffix,
    )


def config_example_path(data_dir):
    return Path(data_dir) / "config.example.json"


def config_path(data_dir):
    return Path(data_dir) / "config.json"


def backup_dir_for_config(data_dir):
    return Path(data_dir) / "backups"


def token_path(data_dir):
    return Path(data_dir) / "workbench.token"


def _default_data_dir():
    root = Path(__file__).resolve().parent.parent
    return Path(os.environ.get("WORKBENCH_DATA_DIR", str(root / "data")))


def _current_system_defaults():
    system = deepcopy(DEFAULT_CONFIG["system"])
    system.update({
        "platform": platform.system() or sys.platform,
        "python_version": platform.python_version(),
    })
    return system


def _canonical_default():
    config = deepcopy(DEFAULT_CONFIG)
    config["system"] = _current_system_defaults()
    return config


def _persistent_config(config):
    """Return the on-disk shape. Runtime system status is never persisted."""
    config = config or {}
    return {
        "version": config.get("version", CONFIG_VERSION),
        "user": deepcopy(config.get("user") or DEFAULT_CONFIG["user"]),
        "advanced": deepcopy(config.get("advanced") or DEFAULT_CONFIG["advanced"]),
    }


def _has_non_persistent_config_keys(payload):
    if not isinstance(payload, dict):
        return False
    return any(key not in ("version", "user", "advanced") for key in payload)


def _safe_runtime_system(trusted_system=None):
    system = {
        key: DEFAULT_CONFIG["system"].get(key)
        for key in SAFE_SYSTEM_FIELDS
    }
    system.update({
        key: _current_system_defaults().get(key, system.get(key))
        for key in SAFE_SYSTEM_FIELDS
    })
    if isinstance(trusted_system, dict):
        for key in SAFE_SYSTEM_FIELDS:
            if key in trusted_system:
                system[key] = trusted_system.get(key)
    _redact_sensitive_mapping(system)
    return system


def merge_runtime_system(config, trusted_status=None):
    merged = deepcopy(config or {})
    merged["system"] = _safe_runtime_system(trusted_status)
    return merged


def ensure_local_runtime(data_dir):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in LOCAL_DIRS:
        (data_dir / name).mkdir(parents=True, exist_ok=True)
    example = config_example_path(data_dir)
    if not example.exists():
        write_json(example, _persistent_config(DEFAULT_CONFIG))
    config = config_path(data_dir)
    if not config.exists():
        write_json(config, _persistent_config(DEFAULT_CONFIG))
    if not token_path(data_dir).exists():
        token_path(data_dir).write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return config


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup_dir = backup_dir_for_config(path.parent)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / (path.name + ".bak")
        shutil.copyfile(path, backup)
    temp = path.with_name(".%s.tmp" % path.name)
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _backup_problem_config(path, label):
    path = Path(path)
    if not path.exists():
        return ""
    stamp = time.strftime("%Y%m%d%H%M%S")
    backup_dir = backup_dir_for_config(path.parent)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / ("%s.%s.%s.bak" % (path.name, label, stamp))
    shutil.copyfile(path, backup)
    return str(backup)


def backup_config_for_migration(data_dir, source_path=None):
    data_dir = Path(data_dir)
    source_path = Path(source_path or config_path(data_dir))
    if not source_path.exists():
        return ""
    backup_dir = backup_dir_for_config(data_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d%H%M%S")
    backup = backup_dir / ("config-before-migration-%s.json" % stamp)
    shutil.copyfile(source_path, backup)
    return str(backup)


def _to_string(value):
    if value is None:
        return ""
    return str(value).strip()


def _to_bool(value, field, errors, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    errors.append(_issue(field, "必须是布尔值", value, "true 或 false"))
    return default


def _parse_legacy_bool(value, field, warnings):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    warnings.append(_issue(field, "旧布尔字段含义不明确，已按安全默认处理", value, "true/false/1/0"))
    return None


def _to_int(value, field, errors, default, min_value=None, max_value=None):
    if isinstance(value, bool):
        errors.append(_issue(field, "必须是整数，不能用布尔值代替", value, _range_label(min_value, max_value)))
        return default
    try:
        if isinstance(value, str):
            text = value.strip()
            if not re.fullmatch(r"[+-]?\d+", text):
                raise ValueError
            parsed = int(text, 10)
        else:
            parsed = int(value)
    except (TypeError, ValueError):
        errors.append(_issue(field, "必须是整数", value, _range_label(min_value, max_value)))
        return default
    if min_value is not None and parsed < min_value:
        errors.append(_issue(field, "低于最小值", value, _range_label(min_value, max_value)))
        return default
    if max_value is not None and parsed > max_value:
        errors.append(_issue(field, "超过最大值", value, _range_label(min_value, max_value)))
        return default
    return parsed


def _parse_config_version(value, warnings, field="version"):
    if value is None:
        warnings.append(_issue(field, "缺少配置版本，已按当前版本处理", value, CONFIG_VERSION))
        return CONFIG_VERSION
    if isinstance(value, bool):
        warnings.append(_issue(field, "配置版本不能是布尔值，已按当前版本处理", value, CONFIG_VERSION))
        return CONFIG_VERSION
    if isinstance(value, int):
        if value == CONFIG_VERSION:
            return value
        warnings.append(_issue(field, "配置版本不受支持，已按当前版本处理", value, CONFIG_VERSION))
        return CONFIG_VERSION
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d+", text):
            parsed = int(text, 10)
            if parsed == CONFIG_VERSION:
                return parsed
        warnings.append(_issue(field, "配置版本格式无效，已按当前版本处理", value, CONFIG_VERSION))
        return CONFIG_VERSION
    warnings.append(_issue(field, "配置版本类型无效，已按当前版本处理", value, CONFIG_VERSION))
    return CONFIG_VERSION


def _is_current_config_version(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == CONFIG_VERSION
    if isinstance(value, str):
        text = value.strip()
        return bool(re.fullmatch(r"\d+", text)) and int(text, 10) == CONFIG_VERSION
    return False


def _to_float(value, field, errors, default, min_value=None, max_value=None, inclusive_min=True):
    if isinstance(value, bool):
        errors.append(_issue(field, "必须是数字，不能用布尔值代替", value, _range_label(min_value, max_value)))
        return default
    try:
        if isinstance(value, str):
            parsed = float(value.strip())
        else:
            parsed = float(value)
    except (TypeError, ValueError):
        errors.append(_issue(field, "必须是数字", value, _range_label(min_value, max_value)))
        return default
    if min_value is not None and (parsed < min_value if inclusive_min else parsed <= min_value):
        errors.append(_issue(field, "低于最小值" if inclusive_min else "必须大于最小值", value, _range_label(min_value, max_value)))
        return default
    if max_value is not None and parsed > max_value:
        errors.append(_issue(field, "超过最大值", value, _range_label(min_value, max_value)))
        return default
    return parsed


def _range_label(min_value, max_value):
    if min_value is None and max_value is None:
        return ""
    if min_value is None:
        return "<= %s" % max_value
    if max_value is None:
        return ">= %s" % min_value
    return "%s 至 %s" % (min_value, max_value)


def _normalize_keywords(value, errors, warnings):
    raw_items = value
    if isinstance(value, str):
        raw_items = re.split(r"[,，\n]+", value)
    if not isinstance(raw_items, list):
        errors.append(_issue("user.keywords", "必须是字符串数组", value, "1 至 %d 个关键词" % MAX_KEYWORDS))
        raw_items = []
    seen = set()
    items = []
    for item in raw_items:
        text = _to_string(item)
        if not text:
            continue
        if len(text) > 50:
            errors.append(_issue("user.keywords", "单个关键词长度不能超过50", text, "1 至 50 个字符"))
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
    if not items:
        errors.append(_issue("user.keywords", "至少需要一个非空关键词", value, "1 至 %d 个关键词" % MAX_KEYWORDS))
        items = deepcopy(DEFAULT_CONFIG["user"]["keywords"])
    if len(items) > MAX_KEYWORDS:
        warnings.append(_issue("user.keywords", "关键词超过建议上限，已保留前%d个" % MAX_KEYWORDS, items, "最多 %d 个" % MAX_KEYWORDS))
        items = items[:MAX_KEYWORDS]
    return items


def _normalize_path(value, field, errors, required=True):
    text = _to_string(value)
    if not text:
        if required:
            errors.append(_issue(field, "路径不能为空", value, "有效本地路径"))
        return ""
    if "\x00" in text:
        errors.append(_issue(field, "路径不能包含空字节", value, "有效本地路径"))
        return ""
    return os.path.normpath(text)


def _normalize_url(value, field, errors, required=True):
    text = _to_string(value)
    if not text:
        if required:
            errors.append(_issue(field, "URL不能为空", value, "http:// 或 https://"))
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        errors.append(_issue(field, "URL必须包含 http:// 或 https:// 协议和主机名", value, "http:// 或 https://"))
        return text
    return text


def _set_nested(config, path, value, changed_fields):
    parts = path.split(".")
    target = config
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    key = parts[-1]
    if target.get(key) != value:
        target[key] = value
        changed_fields.append(path)


def _legacy_has_simulation_conflict(flat):
    dry_value = flat.get("dry_run_collect") if isinstance(flat, dict) else None
    dry = _parse_legacy_bool(dry_value, "dry_run_collect", []) if "dry_run_collect" in (flat or {}) else None
    mode = _to_string((flat or {}).get("mode")).lower()
    return dry is True or mode in ("mock", "dry_run", "simulation")


def _legacy_publish_requested(flat):
    flat = flat or {}
    mode = _to_string(flat.get("mode")).lower()
    publish_enabled = _parse_legacy_bool(flat.get("publish_enabled"), "publish_enabled", []) if "publish_enabled" in flat else None
    return mode == "publish" or publish_enabled is True


def _coerce_margin(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return value
    if parsed > 1:
        return parsed / 100
    return parsed


def _apply_legacy_field(config, key, value, changed_fields, ignored_fields, warnings, legacy_values=None):
    if key in ("category", "keywords", "target_count", "candidate_limit", "purchase_price_min", "purchase_price_max", "max_weight_kg", "auto_season_check", "image_strategy"):
        _set_nested(config, LEGACY_FIELD_MAPPINGS[key][0], value, changed_fields)
        return True
    if key == "minimum_profit_margin":
        _set_nested(config, "user.minimum_profit_margin", _coerce_margin(value), changed_fields)
        return True
    if key in ("min_profit_margin", "market.target_margin_pct"):
        _set_nested(config, "user.minimum_profit_margin", _coerce_margin(value), changed_fields)
        warnings.append(_issue("user.minimum_profit_margin", "旧利润率字段已统一为小数，0.2 表示 20%", value, "0 至 1"))
        return True
    if key == "max_items_per_run":
        _set_nested(config, "advanced.per_run_item_limit", value, changed_fields)
        return True
    if key == "max_pages_per_keyword":
        _set_nested(config, "advanced.per_keyword_page_limit", value, changed_fields)
        _set_nested(config, "advanced.search_max_pages", value, changed_fields)
        return True
    if key == "max_retry":
        _set_nested(config, "advanced.step_retry_count", value, changed_fields)
        return True
    if key == "max_weight_g":
        try:
            converted = float(value) / 1000
        except (TypeError, ValueError):
            converted = value
        _set_nested(config, "user.max_weight_kg", converted, changed_fields)
        warnings.append(_issue("user.max_weight_kg", "旧重量字段 max_weight_g 已按克转换为公斤", value, "kg"))
        return True
    if key == "chrome_profile_dir":
        _set_nested(config, "advanced.browser_user_data_dir", value, changed_fields)
        return True
    if key == "chrome_debug_port":
        _set_nested(config, "advanced.cdp_port", value, changed_fields)
        return True
    if key in ("enable_dedupe", "enable_risk_filter", "enable_title_clean", "enable_image_check", "enable_miaoshou_collect"):
        _set_nested(config, "advanced.%s" % key, value, changed_fields)
        return True
    if key in ("dry_run_collect", "collect_to_box_only", "mode", "real_mode", "live_mode", "publish_enabled", "no_publish"):
        return _apply_legacy_run_mode(config, key, value, changed_fields, ignored_fields, warnings, legacy_values or {})
    ignored_fields.append(key)
    return False


def _apply_legacy_run_mode(config, key, value, changed_fields, ignored_fields, warnings, legacy_values=None):
    legacy_values = legacy_values or {}
    if key == "dry_run_collect":
        parsed = _parse_legacy_bool(value, key, warnings)
        if parsed is True:
            _set_nested(config, "user.run_mode", "simulation", changed_fields)
        elif parsed is False and _parse_legacy_bool(legacy_values.get("collect_to_box_only"), "collect_to_box_only", []) is True:
            if _legacy_publish_requested(legacy_values):
                _set_nested(config, "user.run_mode", "simulation", changed_fields)
                warnings.append(_issue("user.run_mode", "旧配置请求发布，已拒绝并进入 simulation", value, RUN_MODES))
            else:
                _set_nested(config, "user.run_mode", "collect_to_box", changed_fields)
        return True
    if key == "collect_to_box_only":
        parsed = _parse_legacy_bool(value, key, warnings)
        dry = _parse_legacy_bool(legacy_values.get("dry_run_collect"), "dry_run_collect", []) if "dry_run_collect" in legacy_values else None
        if parsed is True and dry is False:
            if _legacy_publish_requested(legacy_values):
                _set_nested(config, "user.run_mode", "simulation", changed_fields)
                warnings.append(_issue("user.run_mode", "旧配置请求发布，已拒绝并进入 simulation", value, RUN_MODES))
            else:
                _set_nested(config, "user.run_mode", "collect_to_box", changed_fields)
        elif parsed is False:
            warnings.append(_issue("advanced.collect_to_box_only", "旧配置试图关闭采集箱限制，已保持安全模式", value, "true"))
        return True
    if key == "mode":
        mode = _to_string(value).lower()
        if mode in ("mock", "dry_run", "simulation"):
            _set_nested(config, "user.run_mode", "simulation", changed_fields)
        elif mode in ("real", "collect_to_box"):
            if _legacy_publish_requested(legacy_values):
                _set_nested(config, "user.run_mode", "simulation", changed_fields)
                warnings.append(_issue("user.run_mode", "旧配置请求发布，已拒绝并进入 simulation", value, RUN_MODES))
            elif _legacy_has_simulation_conflict(legacy_values):
                _set_nested(config, "user.run_mode", "simulation", changed_fields)
                warnings.append(_issue("user.run_mode", "旧运行模式与模拟配置冲突，已进入 simulation", value, RUN_MODES))
            else:
                _set_nested(config, "user.run_mode", "collect_to_box", changed_fields)
        elif mode == "publish":
            _set_nested(config, "user.run_mode", "simulation", changed_fields)
            warnings.append(_issue("user.run_mode", "旧 mode=publish 已被拒绝并降级为 simulation", value, RUN_MODES))
        else:
            _set_nested(config, "user.run_mode", "simulation", changed_fields)
            warnings.append(_issue("user.run_mode", "旧 mode 含义不明确，已进入 simulation", value, RUN_MODES))
        return True
    if key in ("real_mode", "live_mode"):
        _set_nested(config, "user.run_mode", "simulation", changed_fields)
        ignored_fields.append(key)
        warnings.append(_issue("user.run_mode", "%s 含义不明确，已进入 simulation" % key, value, RUN_MODES))
        return True
    if key == "publish_enabled":
        ignored_fields.append(key)
        parsed = _parse_legacy_bool(value, key, warnings)
        if parsed is True:
            warnings.append(_issue("user.run_mode", "publish_enabled=true 被拒绝，当前版本禁止发布模式", value, RUN_MODES))
        _set_nested(config, "user.run_mode", "simulation", changed_fields)
        return True
    if key == "no_publish":
        if value is not True:
            warnings.append(_issue("advanced.no_publish", "旧配置试图关闭 no_publish，已强制保持 true", value, "true"))
        _set_nested(config, "advanced.no_publish", True, changed_fields)
        return True
    return False


def _legacy_source(payload):
    if not isinstance(payload, dict):
        return {}
    source = {}
    for key in (
        "mode",
        "dry_run_collect",
        "collect_to_box_only",
        "no_publish",
        "max_items_per_run",
        "max_pages_per_keyword",
        "keywords",
        "enable_dedupe",
        "enable_risk_filter",
        "enable_title_clean",
        "enable_image_check",
        "enable_miaoshou_collect",
        "max_retry",
        "max_weight_g",
        "chrome_profile_dir",
        "chrome_debug_port",
    ):
        if key in payload:
            source[key] = payload[key]
    legacy = payload.get("legacy")
    if isinstance(legacy, dict):
        source.update(legacy.get("flat", {}) if isinstance(legacy.get("flat"), dict) else {})
    return source


def migrate_legacy_config(values):
    warnings = []
    config = _canonical_default()
    legacy = {}
    changed_fields = []
    ignored_fields = []
    source_version = None
    if not isinstance(values, dict):
        warnings.append(_issue("config", "配置文件不是对象，已使用安全默认配置", values, "JSON object"))
        return {
            "migrated": True,
            "source_version": source_version,
            "target_version": CONFIG_VERSION,
            "changed_fields": [],
            "ignored_fields": [],
            "warnings": warnings,
            "normalized_config": config,
        }

    is_structured = isinstance(values.get("user"), dict) or isinstance(values.get("advanced"), dict)
    if is_structured:
        source_version = values.get("version", CONFIG_VERSION)
        config["documentation"] = _to_string(values.get("documentation")) or CONFIG_DOC
        config["version"] = _parse_config_version(values.get("version"), warnings)
        config["user"].update(values.get("user") or {})
        config["advanced"].update(values.get("advanced") or {})
        legacy = deepcopy(values.get("legacy") or {})
        aliases = {key: values[key] for key in _legacy_source(values) if key in values}
        if aliases:
            legacy.setdefault("flat", {}).update(deepcopy(aliases))
            warnings.append(_issue("legacy.flat", "检测到结构化配置中夹带旧版平铺字段，已保留但不作为主配置覆盖", aliases, "user/advanced"))
            if aliases.get("mode") == "publish" or aliases.get("no_publish") is False or aliases.get("collect_to_box_only") is False:
                warnings.append(_issue("legacy.flat", "旧版字段包含发布或关闭安全开关意图，已忽略并保持安全默认", aliases, "no_publish=true, collect_to_box_only=true"))
            ignored_fields.extend(sorted(aliases))
    else:
        source_version = 0
        legacy["flat"] = deepcopy(values)
        warnings.append(_issue("config", "检测到旧版平铺配置，已迁移到 version/user/advanced/system 结构", "legacy", "version 1"))
        for key, value in values.items():
            if key in LEGACY_FIELD_MAPPINGS or key in _legacy_source(values):
                _apply_legacy_field(config, key, value, changed_fields, ignored_fields, warnings, values)

    for key, value in values.items():
        if key not in ("version", "documentation", "user", "advanced", "system", "legacy") and key not in _legacy_source(values):
            legacy.setdefault("unknown_top_level", {})[key] = value
            ignored_fields.append(key)
            warnings.append(_issue(key, "未知顶层字段，已保留在 legacy 区", value, "version/user/advanced/system"))

    if "system" in values and values.get("system"):
        ignored_fields.append("system")
        warnings.append(_issue("system", "system 为自动检测结果，普通保存不会采用输入值", "[provided]", "由系统检测写入"))

    if legacy:
        config["legacy"] = legacy
    return {
        "migrated": bool(not is_structured or changed_fields or ignored_fields or warnings),
        "source_version": source_version,
        "target_version": CONFIG_VERSION,
        "changed_fields": sorted(set(changed_fields)),
        "ignored_fields": sorted(set(ignored_fields)),
        "warnings": warnings,
        "normalized_config": config,
    }


def validate_config(config):
    migration = migrate_legacy_config(config)
    migrated = migration["normalized_config"]
    warnings = list(migration["warnings"])
    errors = []
    normalized = _canonical_default()
    normalized["documentation"] = CONFIG_DOC

    normalized["version"] = _parse_config_version(migrated.get("version"), warnings)

    user = migrated.get("user") if isinstance(migrated.get("user"), dict) else {}
    advanced = migrated.get("advanced") if isinstance(migrated.get("advanced"), dict) else {}

    for key in user:
        if key not in DEFAULT_CONFIG["user"]:
            warnings.append(_issue("user.%s" % key, "未知普通配置字段，已保留在 legacy 区", user.get(key), sorted(DEFAULT_CONFIG["user"])))
            normalized.setdefault("legacy", {}).setdefault("user", {})[key] = user.get(key)
    for key in advanced:
        if key not in DEFAULT_CONFIG["advanced"]:
            warnings.append(_issue("advanced.%s" % key, "未知高级配置字段，已保留在 legacy 区", advanced.get(key), sorted(DEFAULT_CONFIG["advanced"])))
            normalized.setdefault("legacy", {}).setdefault("advanced", {})[key] = advanced.get(key)

    user_defaults = DEFAULT_CONFIG["user"]
    advanced_defaults = DEFAULT_CONFIG["advanced"]
    for key in user_defaults:
        if key not in user:
            warnings.append(_issue("user.%s" % key, "缺少字段，已使用默认值", None, user_defaults[key]))
    for key in advanced_defaults:
        if key not in advanced:
            warnings.append(_issue("advanced.%s" % key, "缺少字段，已使用默认值", None, advanced_defaults[key]))

    category = _to_string(user.get("category", user_defaults["category"]))
    if not category:
        errors.append(_issue("user.category", "不能为空或只包含空格", user.get("category"), "1 至 100 个字符"))
        category = user_defaults["category"]
    if len(category) > 100:
        errors.append(_issue("user.category", "长度不能超过100", category, "1 至 100 个字符"))
        category = category[:100]
    normalized["user"]["category"] = category
    normalized["user"]["keywords"] = _normalize_keywords(user.get("keywords", user_defaults["keywords"]), errors, warnings)

    target_count = _to_int(user.get("target_count", user_defaults["target_count"]), "user.target_count", errors, user_defaults["target_count"], 1, MAX_TARGET_COUNT)
    candidate_default = min(MAX_CANDIDATE_LIMIT, max(target_count * 4, target_count))
    candidate_source = user.get("candidate_limit", candidate_default)
    candidate_limit = _to_int(candidate_source, "user.candidate_limit", errors, candidate_default, 1, MAX_CANDIDATE_LIMIT)
    if candidate_limit < target_count:
        errors.append(_issue("user.candidate_limit", "必须大于或等于 target_count", candidate_limit, ">= %d" % target_count))
        candidate_limit = candidate_default
    normalized["user"]["target_count"] = target_count
    normalized["user"]["candidate_limit"] = candidate_limit

    price_min = _to_float(user.get("purchase_price_min", user_defaults["purchase_price_min"]), "user.purchase_price_min", errors, user_defaults["purchase_price_min"], 0, None)
    price_max = _to_float(user.get("purchase_price_max", user_defaults["purchase_price_max"]), "user.purchase_price_max", errors, user_defaults["purchase_price_max"], 0, None)
    if price_min > price_max:
        errors.append(_issue("user.purchase_price_min", "最低采购价不得高于最高采购价", price_min, "<= user.purchase_price_max"))
        price_min = user_defaults["purchase_price_min"]
        price_max = user_defaults["purchase_price_max"]
    normalized["user"]["purchase_price_min"] = price_min
    normalized["user"]["purchase_price_max"] = price_max
    normalized["user"]["max_weight_kg"] = _to_float(user.get("max_weight_kg", user_defaults["max_weight_kg"]), "user.max_weight_kg", errors, user_defaults["max_weight_kg"], 0, None, inclusive_min=False)
    normalized["user"]["minimum_profit_margin"] = _to_float(user.get("minimum_profit_margin", user_defaults["minimum_profit_margin"]), "user.minimum_profit_margin", errors, user_defaults["minimum_profit_margin"], 0, 1)
    normalized["user"]["auto_season_check"] = _to_bool(user.get("auto_season_check", user_defaults["auto_season_check"]), "user.auto_season_check", errors, user_defaults["auto_season_check"])

    image_strategy = _to_string(user.get("image_strategy", user_defaults["image_strategy"]))
    if image_strategy not in IMAGE_STRATEGIES:
        errors.append(_issue("user.image_strategy", "不支持的图片策略", image_strategy, IMAGE_STRATEGIES))
        image_strategy = user_defaults["image_strategy"]
    normalized["user"]["image_strategy"] = image_strategy

    run_mode = _to_string(user.get("run_mode", user_defaults["run_mode"]))
    if run_mode == "publish":
        errors.append(_issue("user.run_mode", "当前版本禁止 publish 模式", run_mode, RUN_MODES))
        run_mode = user_defaults["run_mode"]
    elif run_mode not in RUN_MODES:
        errors.append(_issue("user.run_mode", "不支持的运行模式", run_mode, RUN_MODES))
        run_mode = user_defaults["run_mode"]
    normalized["user"]["run_mode"] = run_mode

    normalized["advanced"]["search_max_pages"] = _to_int(advanced.get("search_max_pages", advanced_defaults["search_max_pages"]), "advanced.search_max_pages", errors, advanced_defaults["search_max_pages"], 1, MAX_SEARCH_PAGES)
    normalized["advanced"]["page_load_timeout_seconds"] = _to_float(advanced.get("page_load_timeout_seconds", advanced_defaults["page_load_timeout_seconds"]), "advanced.page_load_timeout_seconds", errors, advanced_defaults["page_load_timeout_seconds"], 1, MAX_TIMEOUT_SECONDS)
    normalized["advanced"]["step_retry_count"] = _to_int(advanced.get("step_retry_count", advanced_defaults["step_retry_count"]), "advanced.step_retry_count", errors, advanced_defaults["step_retry_count"], 0, MAX_STEP_RETRY)
    normalized["advanced"]["task_failure_limit"] = _to_int(advanced.get("task_failure_limit", advanced_defaults["task_failure_limit"]), "advanced.task_failure_limit", errors, advanced_defaults["task_failure_limit"], 1, MAX_TASK_FAILURE_LIMIT)
    normalized["advanced"]["collection_interval_seconds"] = _to_float(advanced.get("collection_interval_seconds", advanced_defaults["collection_interval_seconds"]), "advanced.collection_interval_seconds", errors, advanced_defaults["collection_interval_seconds"], 0, MAX_COLLECTION_INTERVAL_SECONDS)
    normalized["advanced"]["prefer_plugin"] = _to_bool(advanced.get("prefer_plugin", advanced_defaults["prefer_plugin"]), "advanced.prefer_plugin", errors, advanced_defaults["prefer_plugin"])
    normalized["advanced"]["enable_link_fallback"] = _to_bool(advanced.get("enable_link_fallback", advanced_defaults["enable_link_fallback"]), "advanced.enable_link_fallback", errors, advanced_defaults["enable_link_fallback"])
    normalized["advanced"]["browser_path"] = _normalize_path(advanced.get("browser_path", advanced_defaults["browser_path"]), "advanced.browser_path", errors, required=False)
    normalized["advanced"]["browser_user_data_dir"] = _normalize_path(advanced.get("browser_user_data_dir", advanced_defaults["browser_user_data_dir"]), "advanced.browser_user_data_dir", errors)
    normalized["advanced"]["cdp_port"] = _to_int(advanced.get("cdp_port", advanced_defaults["cdp_port"]), "advanced.cdp_port", errors, advanced_defaults["cdp_port"], 1, 65535)
    normalized["advanced"]["alibaba_url"] = _normalize_url(advanced.get("alibaba_url", advanced_defaults["alibaba_url"]), "advanced.alibaba_url", errors)
    normalized["advanced"]["miaoshou_url"] = _normalize_url(advanced.get("miaoshou_url", advanced_defaults["miaoshou_url"]), "advanced.miaoshou_url", errors)
    normalized["advanced"]["plugin_id"] = _to_string(advanced.get("plugin_id", advanced_defaults["plugin_id"]))
    normalized["advanced"]["database_path"] = _normalize_path(advanced.get("database_path", advanced_defaults["database_path"]), "advanced.database_path", errors)
    normalized["advanced"]["log_path"] = _normalize_path(advanced.get("log_path", advanced_defaults["log_path"]), "advanced.log_path", errors)
    normalized["advanced"]["image_inspection_enabled"] = _to_bool(advanced.get("image_inspection_enabled", advanced_defaults["image_inspection_enabled"]), "advanced.image_inspection_enabled", errors, advanced_defaults["image_inspection_enabled"])
    normalized["advanced"]["image_min_width"] = _to_int(advanced.get("image_min_width", advanced_defaults["image_min_width"]), "advanced.image_min_width", errors, advanced_defaults["image_min_width"], 1, MAX_IMAGE_DIMENSION)
    normalized["advanced"]["image_min_height"] = _to_int(advanced.get("image_min_height", advanced_defaults["image_min_height"]), "advanced.image_min_height", errors, advanced_defaults["image_min_height"], 1, MAX_IMAGE_DIMENSION)
    normalized["advanced"]["image_service_url"] = _normalize_url(advanced.get("image_service_url", advanced_defaults["image_service_url"]), "advanced.image_service_url", errors, required=False)
    normalized["advanced"]["image_service_timeout_seconds"] = _to_float(advanced.get("image_service_timeout_seconds", advanced_defaults["image_service_timeout_seconds"]), "advanced.image_service_timeout_seconds", errors, advanced_defaults["image_service_timeout_seconds"], 1, MAX_TIMEOUT_SECONDS)
    dedup_scope = _to_string(advanced.get("dedup_scope", advanced_defaults["dedup_scope"]))
    if dedup_scope not in DEDUP_SCOPES:
        errors.append(_issue("advanced.dedup_scope", "不支持的去重范围", dedup_scope, DEDUP_SCOPES))
        dedup_scope = advanced_defaults["dedup_scope"]
    normalized["advanced"]["dedup_scope"] = dedup_scope

    for key in ("no_publish", "collect_to_box_only", "safety_checks_enabled", "enable_dedupe", "enable_risk_filter", "enable_title_clean", "enable_image_check", "enable_miaoshou_collect"):
        normalized["advanced"][key] = _to_bool(advanced.get(key, advanced_defaults[key]), "advanced.%s" % key, errors, advanced_defaults[key])
    for key in LOCKED_TRUE_ADVANCED_FIELDS:
        if normalized["advanced"][key] is not True:
            errors.append(_issue("advanced.%s" % key, "当前版本必须保持 true，不能通过配置关闭核心安全能力" if key != "no_publish" else "当前版本必须保持 true，不能通过配置启用发布", advanced.get(key), "true"))
            normalized["advanced"][key] = True
    normalized["advanced"]["per_run_item_limit"] = _to_int(advanced.get("per_run_item_limit", advanced_defaults["per_run_item_limit"]), "advanced.per_run_item_limit", errors, advanced_defaults["per_run_item_limit"], 1, MAX_SAFE_ITEMS_PER_RUN)
    normalized["advanced"]["per_keyword_page_limit"] = _to_int(advanced.get("per_keyword_page_limit", advanced_defaults["per_keyword_page_limit"]), "advanced.per_keyword_page_limit", errors, advanced_defaults["per_keyword_page_limit"], 1, MAX_SAFE_PAGES_PER_KEYWORD)

    if "legacy" in migrated:
        normalized["legacy"] = deepcopy(migrated["legacy"])

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "normalized_config": normalized,
    }


def _legacy_view(config, warnings=None, errors=None):
    result = deepcopy(config)
    user = result.get("user") or {}
    advanced = result.get("advanced") or {}
    legacy = result.get("legacy") if isinstance(result.get("legacy"), dict) else {}
    flat = legacy.get("flat") if isinstance(legacy.get("flat"), dict) else {}
    legacy_mode = _to_string(flat.get("mode")) or "real"
    result.update({
        "mode": "mock" if legacy_mode == "mock" else "real",
        "dry_run_collect": user.get("run_mode") == "simulation",
        "collect_to_box_only": True,
        "no_publish": True,
        "max_items_per_run": min(int(advanced.get("per_run_item_limit") or MAX_SAFE_ITEMS_PER_RUN), MAX_SAFE_ITEMS_PER_RUN),
        "max_pages_per_keyword": min(int(advanced.get("per_keyword_page_limit") or MAX_SAFE_PAGES_PER_KEYWORD), MAX_SAFE_PAGES_PER_KEYWORD),
        "keywords": list(user.get("keywords") or []),
        "enable_dedupe": bool(advanced.get("enable_dedupe", True)),
        "enable_risk_filter": bool(advanced.get("enable_risk_filter", True)),
        "enable_title_clean": bool(advanced.get("enable_title_clean", True)),
        "enable_image_check": bool(advanced.get("enable_image_check", True)),
        "enable_miaoshou_collect": bool(advanced.get("enable_miaoshou_collect", True)),
        "max_retry": int(advanced.get("step_retry_count") or 0),
        "chrome_profile_dir": advanced.get("browser_user_data_dir") or "data/chrome-profile",
        "chrome_debug_port": int(advanced.get("cdp_port") or 9222),
    })
    if warnings:
        result["_configWarnings"] = warnings
    if errors:
        result["_configErrors"] = errors
    return result


def _load_payload(path):
    raw = Path(path).read_text(encoding="utf-8")
    if not raw.strip():
        raise json.JSONDecodeError("empty", raw, 0)
    return json.loads(raw)


def load_config(data_dir=None):
    data_dir = Path(data_dir or _default_data_dir())
    missing_before_init = not config_path(data_dir).exists()
    ensure_local_runtime(data_dir)
    path = config_path(data_dir)
    warnings = []
    if missing_before_init:
        warnings.append(_issue("config.json", "配置文件不存在，已加载默认配置", str(path), "保存后生成本地配置"))
    try:
        payload = _load_payload(path)
    except (OSError, json.JSONDecodeError) as exc:
        backup = _backup_problem_config(path, "invalid")
        payload = _canonical_default()
        warnings.append(_issue("config.json", "配置文件无法读取，已加载安全默认配置", str(exc), "有效 JSON 配置"))
        if backup:
            warnings.append(_issue("config.json", "损坏配置已备份", backup, "人工确认后再保存新配置"))
    result = validate_config(payload)
    normalized = result["normalized_config"]
    if not result["valid"]:
        backup = _backup_problem_config(path, "rejected")
        if backup:
            result["warnings"].append(_issue("config.json", "包含无效字段的配置已备份，当前进程使用规范化安全配置", backup, "修正后通过保存接口写入"))
    return _legacy_view(normalized, warnings + result["warnings"], result["errors"])


def get_config(data_dir=None):
    return load_config(data_dir)


def _validation_error_message(result):
    if not result.get("errors"):
        return "配置校验失败"
    return "配置校验失败：%s" % _format_issue(result["errors"][0])


def config_response(config, warnings=None, deprecated=False, trusted_system=None):
    response_warnings = warnings if warnings is not None else config.get("_configWarnings", [])
    response_errors = config.get("_configErrors", [])
    return {
        "ok": True,
        "config": export_safe_config(config, trusted_system=trusted_system),
        "warnings": [_public_issue(item) for item in response_warnings],
        "errors": [_public_issue(item) for item in response_errors],
        "deprecated": bool(deprecated),
    }


def config_error_response(errors=None, warnings=None):
    public_errors = [_public_issue(item) for item in (errors or [])]
    public_warnings = [_public_issue(item) for item in (warnings or [])]
    return {
        "ok": False,
        "error": public_errors[0]["message"] if public_errors else "配置错误",
        "errors": public_errors,
        "warnings": public_warnings,
    }


def save_config(data_dir, values):
    data_dir = Path(data_dir or _default_data_dir())
    ensure_local_runtime(data_dir)
    result = validate_config(values)
    if not result["valid"]:
        raise ConfigValidationError(_validation_error_message(result), result["errors"], result["warnings"])
    normalized = result["normalized_config"]
    _atomic_write_json(config_path(data_dir), _persistent_config(normalized))
    return _legacy_view(normalized, result["warnings"])


def update_config(data_dir, patch, section="user", base_config=None):
    if section not in ("user", "advanced"):
        raise ValueError("配置分区无效：%s" % section)
    if not isinstance(patch, dict):
        raise ValueError("配置更新必须是对象")
    base = validate_config(base_config or load_config(data_dir))["normalized_config"]
    allowed = set(DEFAULT_CONFIG[section])
    update = {}
    ignored = []
    for key, value in patch.items():
        if key == "system":
            ignored.append("system")
            continue
        if key in allowed:
            update[key] = value
        else:
            ignored.append(key)
    merged = deepcopy(base)
    merged[section].update(update)
    saved = save_config(data_dir, merged)
    if ignored:
        saved.setdefault("_configWarnings", []).append(_issue(section, "部分更新忽略非白名单字段", ignored, sorted(allowed)))
    return saved


def get_config_value(path, default=None, data_dir=None, config=None):
    current = config or load_config(data_dir)
    for part in str(path or "").split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def legacy_settings_to_config(settings):
    settings = settings or {}
    config = _canonical_default()
    legacy = {"settings": {}}
    changed_fields = []
    ignored_fields = []
    warnings = []
    mapping = {
        "automation.chrome_path": "advanced.browser_path",
        "automation.chrome_profile_dir": "advanced.browser_user_data_dir",
        "automation.cdp_port": "advanced.cdp_port",
        "automation.alibaba_url": "advanced.alibaba_url",
        "automation.miaoshou_url": "advanced.miaoshou_url",
        "automation.plugin_extension_id": "advanced.plugin_id",
        "image.base_url": "advanced.image_service_url",
        "image.timeout": "advanced.image_service_timeout_seconds",
        "image.retries": "advanced.step_retry_count",
        "market.target_margin_pct": "user.minimum_profit_margin",
    }
    for key, value in settings.items():
        if key in mapping:
            target = mapping[key]
            converted = _coerce_margin(value) if key == "market.target_margin_pct" else value
            _set_nested(config, target, converted, changed_fields)
        elif key.startswith(("evaluation.", "market.", "image.", "text.", "automation.")):
            legacy["settings"][key] = value
            ignored_fields.append(key)
    if legacy["settings"]:
        config["legacy"] = legacy
    if changed_fields:
        warnings.append(_issue("settings", "已从旧 settings 表导入兼容字段", changed_fields, "new config"))
    return {
        "migrated": bool(changed_fields or ignored_fields),
        "source_version": "settings",
        "target_version": CONFIG_VERSION,
        "changed_fields": sorted(set(changed_fields)),
        "ignored_fields": sorted(set(ignored_fields)),
        "warnings": warnings,
        "normalized_config": config,
    }


def merge_config_sources(new_config=None, legacy_config=None, settings=None):
    base = _canonical_default()
    warnings = []
    reports = []
    if settings:
        settings_report = legacy_settings_to_config(settings)
        reports.append(settings_report)
        base = _deep_merge(base, _overlay_changed_config(settings_report))
        warnings.extend(settings_report["warnings"])
    if legacy_config:
        legacy_report = migrate_legacy_config(legacy_config)
        reports.append(legacy_report)
        base = _deep_merge(base, _overlay_changed_config(legacy_report))
        warnings.extend(legacy_report["warnings"])
    if new_config:
        new_result = validate_config(new_config)
        base = _deep_merge(base, new_result["normalized_config"])
        warnings.extend(new_result["warnings"])
    result = validate_config(base)
    result["warnings"].extend(warnings)
    result["migration_reports"] = reports
    return result


def _overlay_changed_config(report):
    source = report.get("normalized_config") or {}
    overlay = {}
    for path in report.get("changed_fields") or []:
        value = get_config_value(path, config=source)
        if value is not None:
            _set_nested(overlay, path, value, [])
    if source.get("legacy"):
        overlay["legacy"] = deepcopy(source["legacy"])
    return overlay


def _deep_merge(base, override):
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def migrate_config_file(data_dir, settings=None, force=False):
    data_dir = Path(data_dir or _default_data_dir())
    config_missing_before_init = not config_path(data_dir).exists()
    ensure_local_runtime(data_dir)
    path = config_path(data_dir)
    payload = {}
    warnings = []
    backup = ""
    try:
        payload = _load_payload(path)
    except (OSError, json.JSONDecodeError) as exc:
        backup = _backup_problem_config(path, "invalid")
        warnings.append(_issue("config.json", "旧配置无法读取，已使用 settings/default 迁移", str(exc), "有效 JSON 配置"))
    version_warnings = []
    parsed_version = _parse_config_version(payload.get("version") if isinstance(payload, dict) else None, version_warnings) if payload else CONFIG_VERSION
    warnings.extend(version_warnings)
    structured = isinstance(payload, dict) and isinstance(payload.get("user"), dict) and parsed_version == CONFIG_VERSION and _is_current_config_version(payload.get("version"))
    settings_seed_available = bool(settings) and config_missing_before_init
    if structured and not force:
        if settings_seed_available:
            settings_report = legacy_settings_to_config(settings)
            changed_fields = settings_report.get("changed_fields") or []
            if changed_fields:
                payload = _deep_merge(payload, _overlay_changed_config(settings_report))
                merged_result = validate_config(payload)
                if not merged_result["valid"]:
                    return {
                        "migrated": False,
                        "source_version": "settings",
                        "target_version": CONFIG_VERSION,
                        "changed_fields": [],
                        "ignored_fields": settings_report.get("ignored_fields") or [],
                        "warnings": warnings + settings_report["warnings"] + merged_result["warnings"],
                        "errors": merged_result["errors"],
                        "normalized_config": merged_result["normalized_config"],
                        "backup_path": backup,
                    }
                _atomic_write_json(path, _persistent_config(merged_result["normalized_config"]))
                return {
                    "migrated": True,
                    "source_version": "settings",
                    "target_version": CONFIG_VERSION,
                    "changed_fields": sorted(set(changed_fields)),
                    "ignored_fields": settings_report.get("ignored_fields") or [],
                    "warnings": warnings + settings_report["warnings"] + merged_result["warnings"],
                    "normalized_config": merged_result["normalized_config"],
                    "backup_path": backup,
                }
        result = validate_config(payload)
        if _has_non_persistent_config_keys(payload) and result["valid"]:
            backup = backup or backup_config_for_migration(data_dir, path)
            _atomic_write_json(path, _persistent_config(result["normalized_config"]))
            return {
                "migrated": True,
                "source_version": payload.get("version"),
                "target_version": CONFIG_VERSION,
                "changed_fields": ["persistent_shape"],
                "ignored_fields": ["system"] if "system" in payload else [],
                "warnings": warnings + result["warnings"] + [_issue("config.json", "已移除非持久化配置字段，system 改为运行时检测返回", sorted([key for key in payload if key not in ("version", "user", "advanced")]), "version/user/advanced")],
                "normalized_config": result["normalized_config"],
                "backup_path": backup,
            }
        return {
            "migrated": False,
            "source_version": payload.get("version"),
            "target_version": CONFIG_VERSION,
            "changed_fields": [],
            "ignored_fields": [],
            "warnings": warnings + result["warnings"],
            "normalized_config": result["normalized_config"],
            "backup_path": backup,
        }
    if isinstance(payload, dict) and (isinstance(payload.get("user"), dict) or isinstance(payload.get("advanced"), dict)):
        if path.exists() and not backup:
            backup = backup_config_for_migration(data_dir, path)
        result = validate_config(payload)
        if not result["valid"]:
            return {
                "migrated": False,
                "source_version": payload.get("version"),
                "target_version": CONFIG_VERSION,
                "changed_fields": [],
                "ignored_fields": [],
                "warnings": warnings + result["warnings"],
                "errors": result["errors"],
                "normalized_config": result["normalized_config"],
                "backup_path": backup,
            }
        _atomic_write_json(path, _persistent_config(result["normalized_config"]))
        return {
            "migrated": True,
            "source_version": payload.get("version"),
            "target_version": CONFIG_VERSION,
            "changed_fields": ["version"],
            "ignored_fields": [],
            "warnings": warnings + result["warnings"],
            "normalized_config": result["normalized_config"],
            "backup_path": backup,
        }
    if path.exists() and not backup:
        backup = backup_config_for_migration(data_dir, path)
    merge_result = merge_config_sources(legacy_config=payload if payload else None, settings=settings)
    if not merge_result["valid"]:
        return {
            "migrated": False,
            "source_version": 0,
            "target_version": CONFIG_VERSION,
            "changed_fields": [],
            "ignored_fields": [],
            "warnings": warnings + merge_result["warnings"],
            "errors": merge_result["errors"],
            "normalized_config": merge_result["normalized_config"],
            "backup_path": backup,
        }
    _atomic_write_json(path, _persistent_config(merge_result["normalized_config"]))
    changed = []
    ignored = []
    for report in merge_result.get("migration_reports", []):
        changed.extend(report.get("changed_fields") or [])
        ignored.extend(report.get("ignored_fields") or [])
    return {
        "migrated": True,
        "source_version": 0,
        "target_version": CONFIG_VERSION,
        "changed_fields": sorted(set(changed)),
        "ignored_fields": sorted(set(ignored)),
        "warnings": warnings + merge_result["warnings"],
        "normalized_config": merge_result["normalized_config"],
        "backup_path": backup,
    }


def reset_config(data_dir=None):
    data_dir = Path(data_dir or _default_data_dir())
    ensure_local_runtime(data_dir)
    config = _canonical_default()
    _atomic_write_json(config_path(data_dir), _persistent_config(config))
    return _legacy_view(config)


def export_safe_config(config=None, trusted_system=None):
    config = config or load_config()
    validation = validate_config(config)
    safe = deepcopy(validation["normalized_config"])
    advanced = safe.get("advanced", {})
    for key in ("browser_path", "browser_user_data_dir", "database_path", "log_path"):
        if advanced.get(key):
            advanced[key] = "<local-path>"
    for section in ("user", "advanced", "system"):
        _redact_sensitive_mapping(safe.get(section, {}))
    safe["system"] = _safe_runtime_system(trusted_system)
    safe.pop("legacy", None)
    return safe


def _redact_sensitive_mapping(mapping):
    if not isinstance(mapping, dict):
        return
    for key, value in list(mapping.items()):
        if SENSITIVE_FIELD_PATTERN.search(str(key)):
            mapping[key] = "***configured***" if value else ""
        elif isinstance(value, dict):
            _redact_sensitive_mapping(value)


def sanitize_config(values):
    result = validate_config(values)
    return _legacy_view(result["normalized_config"], result["warnings"], result["errors"])


def load_or_create_token(data_dir):
    ensure_local_runtime(data_dir)
    path = token_path(data_dir)
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        path.write_text(token, encoding="utf-8")
    return token


def config_status(config):
    config = _legacy_view(validate_config(config)["normalized_config"])
    return {
        "mode": config["mode"],
        "runMode": config["user"]["run_mode"],
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


def assert_real_pipeline_safety(config, context="真实小批量联调"):
    if not config.get("no_publish", True):
        raise RuntimeError("%s 需要 no_publish=true，禁止进入任何可能发布的流程" % context)
    if not (config.get("dry_run_collect", True) or config.get("collect_to_box_only", False)):
        raise RuntimeError("%s 需要 dry_run_collect=true 或 collect_to_box_only=true" % context)
    if int(config.get("max_items_per_run") or 0) > MAX_SAFE_ITEMS_PER_RUN:
        raise RuntimeError("%s 每轮最多 %d 个商品" % (context, MAX_SAFE_ITEMS_PER_RUN))
    if int(config.get("max_pages_per_keyword") or 0) > MAX_SAFE_PAGES_PER_KEYWORD:
        raise RuntimeError("%s 每个关键词最多 %d 页" % (context, MAX_SAFE_PAGES_PER_KEYWORD))
    return True
