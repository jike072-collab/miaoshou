# Module 01 配置 API 契约

本文件记录模块1第4部分后的配置接口约定。当前目标是让配置读取和保存统一进入 `lib/local_config.py`，同时保留旧 `/api/settings` 兼容入口。

## 配置来源

- 主配置文件：`data/config.json`
- 唯一读取入口：`lib/local_config.py::load_config()` / `get_config()`
- 唯一保存入口：`lib/local_config.py::update_config()` / `save_config()`
- 安全导出入口：`lib/local_config.py::export_safe_config()`
- 运行态 system 来源：`app.py::get_runtime_system_status()`
- settings 兼容镜像：`app.py::sync_settings_from_config()`
- 启动迁移入口：`app.py::initialize()` 调用 `migrate_config_file(DATA_DIR, settings=DB.settings())`

## GET /api/config

读取当前统一配置。

响应：

```json
{
  "ok": true,
  "config": {
    "version": 1,
    "user": {},
    "advanced": {},
    "system": {}
  },
  "warnings": [],
  "errors": [],
  "deprecated": false
}
```

说明：

- 返回值由 `config_response(workbench_config())` 生成。
- `config` 经过 `export_safe_config(..., trusted_system=get_runtime_system_status())` 脱敏；`data/config.json` 不持久化 `system`。
- `system` 只返回安全白名单字段：`platform`、`python_version`、`chrome_detected`、`cdp_available`、`alibaba_logged_in`、`miaoshou_logged_in`、`plugin_detected`、`last_environment_check_at`。
- 本机路径字段返回 `<local-path>`。
- `api_key`、`token`、`cookie`、`password`、`secret` 等字段不会返回明文。
- 配置文件不存在时由 `load_config()` 加载默认配置，并在 warnings 中说明。
- 配置损坏时使用安全默认配置，并在 warnings/errors 中说明，不让页面崩溃。

## PUT/POST /api/config

保存普通用户配置。两种方法等价，前端当前使用 `PUT`。

请求：

```json
{
  "values": {
    "category": "鞋类",
    "keywords": ["运动鞋", "凉鞋"],
    "target_count": 50,
    "candidate_limit": 200,
    "purchase_price_min": 0,
    "purchase_price_max": 200,
    "max_weight_kg": 2,
    "minimum_profit_margin": 0.2,
    "auto_season_check": true,
    "image_strategy": "inspect_and_fix",
    "run_mode": "simulation"
  }
}
```

允许字段：

| 字段 | 说明 |
| --- | --- |
| `category` | 商品类目 |
| `keywords` | 搜索关键词数组 |
| `target_count` | 目标采集数量 |
| `candidate_limit` | 候选商品上限 |
| `purchase_price_min` | 最低采购价，人民币元 |
| `purchase_price_max` | 最高采购价，人民币元 |
| `max_weight_kg` | 最大重量，公斤 |
| `minimum_profit_margin` | 最低利润率，小数，`0.2` 表示 20% |
| `auto_season_check` | 是否自动判断季节 |
| `image_strategy` | `original` / `inspect_and_fix` / `regenerate` |
| `run_mode` | `simulation` / `collect_to_box` |

普通接口禁止修改：

- `advanced.*`
- `system.*`
- `no_publish`
- `collect_to_box_only`
- 发布相关字段
- Cookie、token、密码、浏览器会话和 API Key

成功响应：

```json
{
  "ok": true,
  "config": {},
  "warnings": [],
  "errors": [],
  "deprecated": false
}
```

失败响应：

```json
{
  "ok": false,
  "error": "必须是1至500之间的整数",
  "errors": [
    {
      "field": "user.target_count",
      "message": "必须是整数",
      "reason": "必须是整数",
      "value": "abc",
      "allowed": "1 至 500"
    }
  ],
  "warnings": []
}
```

状态码：

- `200`：保存成功。
- `400`：参数错误、校验失败、普通接口试图修改高级配置或系统字段。
- `500`：配置已写入但 settings 兼容同步失败，返回明确错误；不会删除已写入配置文件。

## PUT/POST /api/config/advanced

保存高级配置。当前没有新增独立前端页面，只提供后端契约给后续模块使用。

请求：

```json
{
  "values": {
    "search_max_pages": 2,
    "page_load_timeout_seconds": 30,
    "step_retry_count": 2,
    "collection_interval_seconds": 3,
    "prefer_plugin": true,
    "enable_link_fallback": true,
    "cdp_port": 9222
  }
}
```

说明：

- 只允许 `DEFAULT_CONFIG["advanced"]` 中的字段。
- 仍然不能关闭 `no_publish`、`collect_to_box_only`、`safety_checks_enabled`、`enable_dedupe`、`enable_risk_filter`、`enable_title_clean`。提交 `false` 会返回 400，且不会保存配置或同步 settings。
- 仍然不能启用 `publish`。
- system 字段不能通过该接口修改。

## GET /api/settings

旧兼容读取接口，暂时保留。

当前响应仍为旧平铺 settings 对象，并额外包含：

- `_deprecated: true`
- `_warnings`
- `_config`：来自 `/api/config` 的安全配置
- `image.has_api_key`：只返回是否已配置，不返回密钥

该接口不会成为主配置来源。

## POST /api/settings

旧兼容保存接口，暂时保留。

处理规则：

- 继续保存无法映射到新版配置的 `evaluation.*`、`automation.*`、`image.*`、`text.*`、`market.*` 旧字段。
- 能映射到新 user 配置的旧字段会先转换为 `/api/config` 的普通配置补丁。
- 与新配置重复的旧高级字段会先转换为 `/api/config/advanced` 补丁，不再独立直接写入 settings。
- 不允许启用发布。
- 不允许旧接口覆盖 `system.*`。
- 不允许旧接口反向覆盖新配置中未提交的字段。
- 保存后执行 `sync_settings_from_config()`，让旧业务读取到新配置镜像。

已映射旧字段：

| 旧字段 | 新字段 |
| --- | --- |
| `category` | `user.category` |
| `keywords` | `user.keywords` |
| `target_count` | `user.target_count` |
| `candidate_limit` | `user.candidate_limit` |
| `min_price` / `purchase_price_min` | `user.purchase_price_min` |
| `max_price` / `purchase_price_max` | `user.purchase_price_max` |
| `weight_limit` / `max_weight_kg` | `user.max_weight_kg` |
| `profit_margin` / `minimum_profit_margin` | `user.minimum_profit_margin` |
| `auto_season_check` | `user.auto_season_check` |
| `image_mode` / `image_strategy` | `user.image_strategy` |
| `automation.mode=dry_run/simulation` | `user.run_mode=simulation` |
| `automation.mode=live/collect_to_box` | `user.run_mode=collect_to_box` |
| `automation.cdp_port` | `advanced.cdp_port` |
| `automation.chrome_profile_dir` | `advanced.browser_user_data_dir` |
| `automation.chrome_path` | `advanced.browser_path` |
| `automation.alibaba_url` | `advanced.alibaba_url` |
| `automation.miaoshou_url` | `advanced.miaoshou_url` |
| `automation.plugin_extension_id` | `advanced.plugin_id` |
| `image.base_url` | `advanced.image_service_url` |
| `image.timeout` | `advanced.image_service_timeout_seconds` |
| `image.retries` | `advanced.step_retry_count` |
| `market.target_margin_pct` | `user.minimum_profit_margin` |

`market.target_margin_pct` 必须是 0 至 100 的数字百分比，例如 `20` 表示 20%，会转换为 `user.minimum_profit_margin=0.2`。非法字符串、空字符串或 `null` 返回 400，字段为 `market.target_margin_pct`，不会写入 `config.json` 或 settings。

## 启动初始化

`initialize()` 执行：

1. `ensure_local_runtime(DATA_DIR)`
2. `migrate_config_file(DATA_DIR, settings=DB.settings())`
3. 迁移成功时输出安全日志，只打印版本、changed/ignored 字段名
4. `sync_settings_from_config()`；`apply_config_to_settings` 仅保留为兼容别名
5. 继续原有数据库兼容迁移和任务恢复标记

启动日志不输出：

- API Key
- token
- Cookie
- 密码
- 完整浏览器会话

## 当前限制

- 尚未替换所有旧业务模块中的 `DB.setting()` 读取。
- `/api/settings` 仍然存在，用于旧页面和旧业务兼容。
- `system` 检测结果不可通过普通/高级配置 API 修改，当前仅从后端可信检测函数合并并安全导出白名单字段。
- 发布、铺货、五国版本等旧功能仍在代码中，模块1不删除。
