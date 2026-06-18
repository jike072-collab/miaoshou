# Module 01 配置参考

本文件是统一配置系统的使用参考。实现入口位于 `lib/local_config.py`，配置接口契约见 `docs/module-01/api-contract.md`。

## 配置文件位置

| 文件 | 用途 | Git 状态 |
| --- | --- | --- |
| `data/config.example.json` | 可提交的示例配置 | 已跟踪 |
| `data/config.json` | 本机真实配置 | 被 `.gitignore` 忽略 |
| `data/backups/config.json.bak` | 最近一次保存前备份 | 被 `.gitignore` 忽略 |
| `data/backups/config.json.*.bak` | 损坏或无效配置备份 | 被 `.gitignore` 忽略 |
| `data/backups/config-before-migration-*.json` | 旧配置迁移前备份 | 被 `.gitignore` 忽略 |

首次安装时可以从示例配置开始：

```bash
cp data/config.example.json data/config.json
```

如果未手动复制，程序启动时会通过 `ensure_local_runtime()` 创建本地配置。

## 配置结构

```json
{
  "version": 1,
  "documentation": "docs/module-01/config-model.md",
  "user": {},
  "advanced": {},
  "system": {}
}
```

- `user`：普通用户可编辑的最小任务配置。
- `advanced`：高级配置和安全开关，默认值即可运行模拟模式。
- `system`：系统检测结果，只读，不接受普通保存接口写入。

## 普通字段

| 字段 | 默认值 | 类型 | 单位/说明 |
| --- | --- | --- | --- |
| `category` | `鞋类` | string | 商品类目，1 至 100 个字符 |
| `keywords` | `["运动鞋","透气鞋","凉鞋","防滑鞋"]` | string[] | 搜索关键词，去空、去重，最多 20 个 |
| `target_count` | `50` | int | 目标采集数量，1 至 500 |
| `candidate_limit` | `200` | int | 候选商品上限，必须大于等于 `target_count`，最多 2000 |
| `purchase_price_min` | `0` | number | 最低采购价，人民币元 |
| `purchase_price_max` | `200` | number | 最高采购价，人民币元 |
| `max_weight_kg` | `2` | number | 最大重量，公斤，必须大于 0 |
| `minimum_profit_margin` | `0.2` | number | 最低利润率，小数，`0.2` 表示 20% |
| `auto_season_check` | `true` | bool | 是否自动判断季节 |
| `image_strategy` | `inspect_and_fix` | enum | `original` / `inspect_and_fix` / `regenerate` |
| `run_mode` | `simulation` | enum | `simulation` / `collect_to_box` |

当前版本禁止 `run_mode=publish`。

## 高级字段

| 字段 | 默认值 | 类型 | 说明 |
| --- | --- | --- | --- |
| `search_max_pages` | `2` | int | 每个关键词最多搜索页数 |
| `page_load_timeout_seconds` | `30` | number | 页面加载超时秒数 |
| `step_retry_count` | `2` | int | 单步骤重试次数 |
| `task_failure_limit` | `10` | int | 单次任务失败上限 |
| `collection_interval_seconds` | `3` | number | 采集间隔秒数 |
| `prefer_plugin` | `true` | bool | 优先使用妙手插件 |
| `enable_link_fallback` | `true` | bool | 插件失败后允许链接采集兜底 |
| `browser_path` | `""` | string | Chrome 可执行文件路径，可为空 |
| `browser_user_data_dir` | `data/chrome-profile` | string | 专用 Chrome 用户目录 |
| `cdp_port` | `9222` | int | Chrome DevTools 端口，1 至 65535 |
| `alibaba_url` | `https://www.1688.com/` | URL | 1688 入口 |
| `miaoshou_url` | `https://erp.91miaoshou.com/` | URL | 妙手入口 |
| `plugin_id` | `""` | string | 妙手插件 ID，可为空 |
| `database_path` | `data/workbench.db` | string | SQLite 数据库路径 |
| `log_path` | `data/logs` | string | 日志目录 |
| `image_inspection_enabled` | `true` | bool | 是否启用图片检查 |
| `image_min_width` | `600` | int | 图片最小宽度 |
| `image_min_height` | `600` | int | 图片最小高度 |
| `image_service_url` | `""` | URL/string | 图片服务地址，可为空 |
| `image_service_timeout_seconds` | `30` | number | 图片服务超时秒数 |
| `dedup_scope` | `all` | enum | `local` / `history` / `all` |
| `no_publish` | `true` | bool | 安全开关，必须为 true |
| `collect_to_box_only` | `true` | bool | 当前版本只允许采集到妙手采集箱 |
| `safety_checks_enabled` | `true` | bool | 安全检查默认开启 |
| `enable_dedupe` | `true` | bool | 去重默认开启 |
| `enable_risk_filter` | `true` | bool | 风险筛选默认开启 |
| `enable_title_clean` | `true` | bool | 标题清洗默认开启 |
| `enable_image_check` | `true` | bool | 图片检查默认开启 |
| `enable_miaoshou_collect` | `true` | bool | 妙手采集默认开启 |
| `per_run_item_limit` | `10` | int | 兼容旧流程的小批量安全上限 |
| `per_keyword_page_limit` | `2` | int | 兼容旧流程的每词页数安全上限 |

高级配置接口仍会强制：

- `no_publish=true`
- `collect_to_box_only=true`
- `safety_checks_enabled=true`
- `enable_dedupe=true`
- `enable_risk_filter=true`
- `enable_title_clean=true`
- 不能出现 `publish` 运行模式

## 系统字段

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `platform` | 自动检测 | 操作系统 |
| `python_version` | 自动检测 | Python 版本 |
| `chrome_detected` | 自动检测 | 是否检测到 Chrome |
| `cdp_available` | 自动检测 | CDP 是否可连接 |
| `alibaba_logged_in` | 自动检测 | 1688 登录状态 |
| `miaoshou_logged_in` | 自动检测 | 妙手登录状态 |
| `plugin_detected` | 自动检测 | 妙手插件状态 |
| `last_environment_check_at` | 自动检测 | 最近检测时间 |

普通保存接口和高级保存接口都不能修改 `system.*`。

`/api/config` 只返回安全 system 字段：`platform`、`python_version`、`chrome_detected`、`cdp_available`、`alibaba_logged_in`、`miaoshou_logged_in`、`plugin_detected`、`last_environment_check_at`。完整本机路径、Cookie、token、密码和 API Key 不会返回。

## 运行模式

| 模式 | 含义 |
| --- | --- |
| `simulation` | 仅本地模拟，不执行妙手真实采集 |
| `collect_to_box` | 真实采集到妙手采集箱，不执行最终发布 |

当前版本不支持：

- 自动发布
- 最终发布确认
- 多店铺自动铺货发布
- 绕过验证码或登录校验

## 迁移规则

迁移入口：

- `migrate_legacy_config(values)`
- `migrate_config_file(data_dir, settings=None, force=False)`
- `legacy_settings_to_config(settings)`

主要映射见 `docs/module-01/legacy-config-mapping.md`。重要规则：

- 旧平铺 `keywords` 迁移到 `user.keywords`。
- 旧 `max_weight_g` 按克转为 `user.max_weight_kg`。
- 旧利润率百分数转为小数，例如 `25` 转为 `0.25`。
- `mode=mock/dry_run/simulation` 或 `dry_run_collect=true` 转为 `simulation`。
- `mode=real/collect_to_box` 且没有模拟冲突时转为 `collect_to_box`。
- `dry_run_collect=false` 且 `collect_to_box_only=true` 转为 `collect_to_box`。
- 含义不明确的 `real_mode`、`live_mode` 转为 `simulation` 并产生警告。
- `mode=publish`、`publish_enabled=true` 会被拒绝并降级到 `simulation`，不会生成发布模式。
- `true`、`1`、`"true"`、`"1"` 视为 true；`false`、`0`、`"false"`、`"0"` 视为 false；其他旧布尔值产生 warning。
- 未识别字段保留在 `legacy` 区或 settings 兼容镜像，并产生 warning。

迁移前会备份旧文件到：

```text
data/backups/config-before-migration-YYYYMMDDHHMMSS.json
```

## 配置损坏恢复

当 `data/config.json` 缺失、为空、JSON 损坏或字段非法时：

1. 程序不会直接崩溃。
2. 损坏文件会备份到 `data/backups/config.json.invalid.*.bak` 或 `data/backups/config.json.rejected.*.bak`。
3. 当前进程加载安全默认配置。
4. API 返回明确 warnings/errors。
5. 不会自动覆盖原损坏文件，需用户确认保存后再写入。

保存配置时使用安全写入：

1. 校验输入。
2. 写临时文件。
3. 原子替换 `data/config.json`。
4. 保留最近一次 `data/backups/config.json.bak`。
5. 同步必要 settings 兼容字段。

## 敏感配置

不得写入配置文件或日志：

- 1688 密码
- 妙手密码
- Cookie
- Authorization
- token
- API Key
- 浏览器完整 Profile

图片 API Key 继续由 `lib/keychain.py` 管理，API 只返回 `image.has_api_key` 这类布尔状态。`export_safe_config()` 会把敏感字段显示为 `***configured***` 或直接移除。
