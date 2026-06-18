# 模块1统一配置模型

本文件说明当前配置服务的目标结构。实际读取、校验和保存入口位于 `lib/local_config.py`。

## 唯一入口

后续业务代码应通过以下函数读取或保存配置：

- `load_config(data_dir=None)`
- `get_config(data_dir=None)`
- `save_config(data_dir, values)`
- `validate_config(config)`
- `reset_config(data_dir=None)`
- `migrate_legacy_config(values)`
- `export_safe_config(config=None, trusted_system=None)`

本阶段为了兼容旧代码，`load_config()` 返回分层配置，同时附带旧字段别名，例如 `keywords`、`max_items_per_run`、`chrome_debug_port`、`no_publish`。

## 结构

配置文件使用 version 1：

```json
{
  "version": 1,
  "user": {},
  "advanced": {}
}
```

`data/config.example.json` 与真实 `data/config.json` 只包含可持久化字段：`version`、`user`、`advanced`。`system` 是运行时检测结果，只在 API 安全导出时由后端可信检测函数合并。真实 `data/config.json` 属于本机数据，继续由 `.gitignore` 忽略。

## 普通配置

`user` 是普通用户可见配置：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `category` | string | `鞋类` | 商品类目，1 至 100 个字符 |
| `keywords` | string[] | `运动鞋` 等 | 搜索关键词，自动去空、去重，最多 20 个 |
| `target_count` | int | `50` | 目标采集数量，1 至 500 |
| `candidate_limit` | int | `200` | 候选上限，必须大于等于 `target_count`，最多 2000 |
| `purchase_price_min` | number | `0` | 采购最低价，单位人民币元 |
| `purchase_price_max` | number | `200` | 采购最高价，单位人民币元 |
| `max_weight_kg` | number | `2` | 最大重量，单位公斤，必须大于 0 |
| `minimum_profit_margin` | number | `0.2` | 最低利润率，小数格式，`0.2` 表示 20% |
| `auto_season_check` | bool | `true` | 是否启用季节判断 |
| `image_strategy` | enum | `inspect_and_fix` | 允许 `original`、`inspect_and_fix`、`regenerate` |
| `run_mode` | enum | `simulation` | 允许 `simulation`、`collect_to_box`，禁止 `publish` |

## 高级配置

`advanced` 使用安全默认值，普通页面默认不应展示。

主要字段包括：

- 搜索和任务：`search_max_pages`、`page_load_timeout_seconds`、`step_retry_count`、`task_failure_limit`、`collection_interval_seconds`
- 妙手采集：`prefer_plugin`、`enable_link_fallback`
- 本地环境：`browser_path`、`browser_user_data_dir`、`cdp_port`、`alibaba_url`、`miaoshou_url`、`plugin_id`、`database_path`、`log_path`
- 图片：`image_inspection_enabled`、`image_min_width`、`image_min_height`、`image_service_url`、`image_service_timeout_seconds`
- 去重和安全：`dedup_scope`、`no_publish`、`collect_to_box_only`、`safety_checks_enabled`
- 兼容旧流程：`enable_dedupe`、`enable_risk_filter`、`enable_title_clean`、`enable_image_check`、`enable_miaoshou_collect`、`per_run_item_limit`、`per_keyword_page_limit`

安全字段固定要求：

- `no_publish` 必须为 `true`
- `collect_to_box_only` 必须为 `true`
- `safety_checks_enabled` 必须为 `true`
- `enable_dedupe` 必须为 `true`
- `enable_risk_filter` 必须为 `true`
- `enable_title_clean` 必须为 `true`
- `run_mode` 不能是 `publish`
- 配置层不会保存账号密码、Cookie、Workbench token 或 API Key

## 系统字段

`system` 只表示自动检测结果，例如：

- `platform`
- `python_version`
- `chrome_detected`
- `cdp_available`
- `alibaba_logged_in`
- `miaoshou_logged_in`
- `plugin_detected`
- `last_environment_check_at`

普通 `save_config()` 不采用用户传入的 `system` 值，也不会把 `system` 写入 `data/config.json`，避免把登录态、检测态或本机状态当作用户配置保存。

API 返回配置时通过 `app.py::get_runtime_system_status()` 合并可信运行状态，只安全导出 `platform`、`python_version`、`chrome_detected`、`cdp_available`、`alibaba_logged_in`、`miaoshou_logged_in`、`plugin_detected`、`last_environment_check_at`。完整 Chrome 路径、浏览器 Profile、Cookie、token、密码和 API Key 不返回。

## 校验与恢复

`validate_config()` 返回：

- `valid`
- `errors`
- `warnings`
- `normalized_config`

错误和警告都包含字段路径、原因、当前值和合法范围。保存时若有错误会抛出 `ValueError`，不会覆盖原配置。

配置读取时如果发现 JSON 损坏、空文件或无法读取，会备份原文件到 `data/backups/` 并加载安全默认配置。保存时先写临时文件，再原子替换，并在 `data/backups/config.json.bak` 保留最近一次备份。

## 旧配置兼容

旧版平铺字段会迁移到 `user` 或 `advanced`：

- `keywords` -> `user.keywords`
- `max_items_per_run` -> `advanced.per_run_item_limit`
- `max_pages_per_keyword` -> `advanced.per_keyword_page_limit`
- `max_retry` -> `advanced.step_retry_count`
- `chrome_profile_dir` -> `advanced.browser_user_data_dir`
- `chrome_debug_port` -> `advanced.cdp_port`

旧字段仍通过兼容别名返回，后续模块可以逐步把业务代码迁移到分层字段。
