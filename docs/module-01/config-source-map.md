# 模块1实施前配置来源地图

审计时间：2026-06-18

本文件只做配置现状确认，不修改业务代码。

## 1. 总览

当前配置至少分为 5 类来源：

1. 本地 JSON 主配置：`data/config.json` / `lib/local_config.py`
2. SQLite settings：`lib/database.py` 中的 `settings` 表
3. 前端 settings 表单：`static/index.html` + `static/app.js`
4. 代码硬编码默认值：`lib/database.py`、`lib/local_config.py`、`lib/browser_manager.py`、`lib/real1688_adapter.py`、`lib/real_miaoshou_adapter.py`、`lib/automation.py`
5. 敏感配置外部存储：`lib/keychain.py` 使用 macOS Keychain

## 2. 配置字段地图

| 配置字段 | 当前来源 | 当前读取位置 | 当前保存位置 | 是否重复 | 新配置路径 | 用户层级 | 迁移方式 | 是否敏感 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `mode` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py`、`static/app.js` | `POST /api/config` -> `save_config()` | 与 `automation.mode` 冲突 | 基础任务配置 | 普通 | 保留 JSON 主配置；settings 侧仅做兼容桥 | 否 |
| `dry_run_collect` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py`、`lib/real_miaoshou_adapter.py`、`lib/automation.py` | `POST /api/config` | 与 `collect_to_box_only`、`automation.mode` 有语义重叠 | 安全/基础任务配置 | 安全默认，不建议关闭 | 保留 JSON 主配置；后续明确 simulation/collect_to_box/publish | 否 |
| `collect_to_box_only` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py`、`lib/real_miaoshou_adapter.py` | `POST /api/config` | 与 `dry_run_collect`、`automation.mode` 重叠 | 安全配置 | 安全默认，不建议关闭 | 保留 JSON 主配置；作为真实采集箱安全模式 | 否 |
| `no_publish` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py`、`lib/real_miaoshou_adapter.py`、`lib/automation.py`、`tests/test_no_publish_guard.py` | `POST /api/config` | 与 `automation.publish_recipe`、`automation.mode` 冲突 | 安全硬开关 | 安全硬开关 | 保留 JSON 主配置，不进入普通关闭项 | 否 |
| `max_items_per_run` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`lib/real1688_adapter.py`、`app.py`、`static/app.js` | `POST /api/config` | 与部分适配器内置上限重复 | 基础任务配置 | 普通 | JSON 主配置为准；适配器二次上限作为硬限额 | 否 |
| `max_pages_per_keyword` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`lib/real1688_adapter.py`、`app.py`、`static/app.js` | `POST /api/config` | 与适配器页数限制重复 | 自动化配置/基础任务配置 | 普通 | JSON 主配置为准；适配器保留硬上限 | 否 |
| `keywords` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`lib/real1688_adapter.py`、`app.py`、`static/app.js`、`tests/test_real1688_adapter.py` | `POST /api/config` | 与页面手工找品输入重复 | 基础任务配置 | 普通 | JSON 主配置为准；页面快速输入仅作辅助 | 否 |
| `enable_dedupe` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py`、`lib/real_miaoshou_adapter.py` | `POST /api/config` | 与旧手工去重按钮重复 | 自动化配置 | 普通默认开启 | JSON 主配置为准 | 否 |
| `enable_risk_filter` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py` | `POST /api/config` | 与旧评分/预检重复 | 自动化配置 | 普通默认开启 | JSON 主配置为准 | 否 |
| `enable_title_clean` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py`、`lib/real1688_adapter.py` | `POST /api/config` | 与手工标题清洗重复 | 自动化配置 | 普通默认开启 | JSON 主配置为准 | 否 |
| `enable_image_check` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py` | `POST /api/config` | 与旧图片工厂人工审核重复 | 自动化配置 | 普通默认开启 | JSON 主配置为准 | 否 |
| `enable_miaoshou_collect` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py`、`lib/real_miaoshou_adapter.py` | `POST /api/config` | 与旧“开始采集”按钮重叠 | 自动化配置 | 普通默认开启 | JSON 主配置为准 | 否 |
| `max_retry` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`app.py`、`tests/test_no_publish_guard.py` | `POST /api/config` | 与图片重试、失败重试语义重叠 | 自动化配置/高级 | 普通默认值 | JSON 主配置为准；后续分解到步骤级重试 | 否 |
| `chrome_profile_dir` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`lib/browser_manager.py`、`app.py`、`tests/test_browser_manager.py` | `POST /api/config` | 与 `automation.chrome_profile_dir` 重复 | 环境配置 | 系统/普通隐藏 | JSON 主配置为准；settings 侧仅兼容 | 是，目录含登录态 |
| `chrome_debug_port` | `data/config.json`、`DEFAULT_CONFIG` | `lib/local_config.py`、`lib/browser_manager.py`、`app.py`、`tests/test_browser_manager.py` | `POST /api/config` | 与 `automation.cdp_port` 重复 | 环境配置 | 高级/系统 | JSON 主配置为准；settings 侧仅兼容 | 否 |
| `automation.mode` | `settings` 表 | `lib/automation.py`、`app.py`、`tests/test_local_config.py` | `POST /api/settings` | 与 JSON `mode` 语义冲突 | 高级自动化配置 | 高级 | 模块1应把它收为兼容桥，避免普通页直改 | 否 |
| `automation.chrome_path` | `settings` 表 | `lib/automation.py`、`lib/browser_manager.py`、`tests/test_automation.py` | `POST /api/settings` | 与 `chrome_profile_dir`/`chrome_debug_port` 无直接重复，但属于同一环境组 | 环境配置 | 高级 | 作为兼容字段保留，后续统一到环境配置 | 否 |
| `automation.cdp_port` | `settings` 表 | `lib/automation.py`、`lib/browser_manager.py`、`app.py`、`tests/test_browser_manager.py` | `POST /api/settings` | 与 `chrome_debug_port` 重复 | 环境配置 | 高级 | 兼容迁移到统一环境配置 | 否 |
| `automation.miaoshou_url` | `settings` 表 | `lib/automation.py`、`lib/browser_manager.py`、`lib/real_miaoshou_adapter.py` | `POST /api/settings` | 与 JSON config 的默认值和 `app.py` 默认 URL 重复 | 环境配置 | 高级 | 作为兼容字段保留，统一读取入口应优先它或统一配置层 | 否 |
| `automation.alibaba_url` | `settings` 表 | `lib/automation.py`、`lib/browser_manager.py`、`lib/real1688_adapter.py` | `POST /api/settings` | 与 JSON config 和代码默认值重复 | 环境配置 | 高级 | 兼容迁移到统一环境配置 | 否 |
| `automation.plugin_unpack_dir` | `settings` 表 | `lib/automation.py`、`tests/test_automation.py` | `POST /api/settings` | 与插件 ID / 旧插件配置组合重复 | 高级自动化配置 | 高级 | 继续保留为高级设置 | 否 |
| `automation.plugin_extension_id` | `settings` 表 | `lib/automation.py`、`lib/browser_manager.py`、`tests/test_automation.py` | `POST /api/settings` | 与 `plugin_unpack_dir` 及插件识别逻辑重复 | 高级自动化配置 | 高级 | 保留兼容字段 | 否 |
| `automation.node_path` | `settings` 表 | `lib/automation.py`、`lib/real1688_adapter.py`、`lib/real_miaoshou_adapter.py`、`tests/test_automation.py` | `POST /api/settings` | 与 bundled runtime 路径和系统 PATH 重复 | 高级自动化配置 | 高级 | 保留兼容字段，后续可自动检测 | 否 |
| `automation.plugin_collect_texts` | `settings` 表 | `lib/automation.py` | `POST /api/settings` | 与 CDP runner 的动作文本重复 | 高级自动化配置 | 高级 | 保留 | 否 |
| `automation.plugin_success_texts` | `settings` 表 | `lib/automation.py` | `POST /api/settings` | 同上 | 高级自动化配置 | 高级 | 保留 | 否 |
| `automation.miaoshou_box_recipe` | `settings` 表 | `lib/automation.py`、`lib/real_miaoshou_adapter.py`、`tests/test_real_miaoshou_adapter.py` | `POST /api/settings`、`POST /api/config` 无直接写入 | 与 `collection_recipe`、`link_collection_recipe`、`publish_recipe` 同属动作配方 | 高级自动化配置 | 仅高级 | 保留兼容字段，但普通页应隐藏 | 否 |
| `automation.collection_recipe` | `settings` 表 | `lib/automation.py`、`lib/real_miaoshou_adapter.py` | `POST /api/settings` | 与 `miaoshou_box_recipe` / `link_collection_recipe` 重叠 | 高级自动化配置 | 高级 | 保留兼容字段 | 否 |
| `automation.link_collection_recipe` | `settings` 表 | `lib/automation.py`、`lib/real_miaoshou_adapter.py` | `POST /api/settings` | 与 `collection_recipe` 重叠 | 高级自动化配置 | 高级 | 保留兼容字段 | 否 |
| `automation.publish_recipe` | `settings` 表 | `lib/automation.py`、`app.py`、`tests/test_no_publish_guard.py` | `POST /api/settings`、`POST /api/config` 不应触发真实发布 | 与安全边界强冲突 | 暂停/隐藏 | 保留底层字段但不在普通页面暴露 | 否，但极高风险 |
| `image.protocol` | `settings` 表 | `lib/image_gateway.py`、`tests/test_image_gateway.py` | `POST /api/settings` | 与 `image.base_url/path/model` 同组 | 图片高级配置 | 高级 | 保留 | 否 |
| `image.base_url` | `settings` 表 | `lib/image_gateway.py`、`lib/text_gateway.py`、`app.py`、`scripts/selfcheck.py` | `POST /api/settings` | 与 Keychain / relay 配置组合 | 图片高级配置 | 高级 | 保留 | 否 |
| `image.path` | `settings` 表 | `lib/image_gateway.py`、`lib/text_gateway.py` | `POST /api/settings` | 与 `image.request_template` 关联 | 图片高级配置 | 高级 | 保留 | 否 |
| `image.model` | `settings` 表 | `lib/image_gateway.py`、`app.py` | `POST /api/settings` | 与 `image.request_template` 关联 | 图片高级配置 | 高级 | 保留 | 否 |
| `image.timeout` | `settings` 表 | `lib/image_gateway.py`、`lib/text_gateway.py`、`tests/test_image_gateway.py` | `POST /api/settings` | 与 `text_gateway` 共用 | 图片/文本高级配置 | 高级 | 保留 | 否 |
| `image.retries` | `settings` 表 | `app.py`、`lib/image_gateway.py` | `POST /api/settings` | 与 `max_retry` 语义重叠 | 图片高级配置 | 高级 | 保留 | 否 |
| `image.concurrency` | `settings` 表 | `app.py` `GENERATION_SLOTS` | `POST /api/settings` | 与运行时 semaphore 绑定 | 图片高级配置 | 高级 | 保留但重启后生效 | 否 |
| `image.request_template` | `settings` 表 | `lib/image_gateway.py`、`static/app.js` | `POST /api/settings` | 与 `image.base_url/path/model` 共同定义接口协议 | 开发者/高级 | 高级 | 保留 | 可能间接影响请求结构 |
| `image.response_path`、`image.task_id_path`、`image.query_path`、`image.status_path`、`image.completed_statuses`、`image.failed_statuses`、`image.poll_interval` | `settings` 表 | `lib/image_gateway.py` | `POST /api/settings` | 同属图片 relay/异步任务协议 | 开发者/高级 | 高级 | 保留 | 否 |
| `text.path`、`text.model` | `settings` 表 | `lib/text_gateway.py`、`app.py` | `POST /api/settings` | 与图片 relay 相关但属于文本服务 | 高级 | 高级 | 保留 | 否 |
| `market.*.exchange`、`market.*.shipping_cny`、`market.platform_fee_pct`、`market.target_margin_pct` | `settings` 表 | `app.py`、`lib/evaluation.py`、`static/index.html`、`tests/test_batch.py` | `POST /api/settings` | 与新主流程的统一准入有重叠，且属于旧五国/铺货体系 | 旧需求/高级 | 高级/隐藏 | 后续可迁移到高级或移出主流程 | 否 |
| `evaluation.threshold`、`evaluation.min_confidence`、`evaluation.min_margin` | `settings` 表 | `app.py`、`lib/evaluation.py`、`tests/test_evaluation.py` | `POST /api/settings` | 与新主流程统一准入门槛相关 | 评估门槛 | 高级 | 保留，但模块1需明确是否还要保留入口 | 否 |

## 3. 直接读 settings 的业务位置

- `app.py`
  - 评估门槛、价格/利润、图片 relay、市场汇率/运费、自动化控制台、自检、发布相关校验。
- `lib/automation.py`
  - Chrome 路径、CDP 端口、妙手/1688 地址、插件目录、插件文本、采集/发布配方、node 路径、自动化模式。
- `lib/browser_manager.py`
  - `automation.cdp_port`、`automation.miaoshou_url`、`automation.alibaba_url`、`automation.node_path`。
- `lib/real1688_adapter.py`
  - `automation.node_path`、`keywords` 主要来自 JSON config。
- `lib/real_miaoshou_adapter.py`
  - `automation.miaoshou_url`、`automation.miaoshou_box_recipe`、`automation.collection_recipe`、`automation.link_collection_recipe`、`automation.node_path`。
- `lib/image_gateway.py`
  - `image.*` relay 配置。
- `lib/text_gateway.py`
  - `text.*` 与 `image.timeout`。
- `tests/**`
  - 大量测试显式覆盖 `no_publish`、`max_items_per_run`、`max_pages_per_keyword`、`automation.*`、`image.*`。

## 4. 直接读 config 的业务位置

- `app.py`
  - `workbench_config()`、`apply_config_to_settings()`、`local_status()`、`assert_real_pipeline_safety()`、`reject_unsafe_publish_payload()`、`/api/config`。
- `lib/browser_manager.py`
  - `local_config()`、`debug_port()`。
- `lib/real1688_adapter.py`
  - `config()`、`normalize_limits()`、`run_once()`、`save_results()`。
- `lib/real_miaoshou_adapter.py`
  - `config()`、`validate_candidate()`、`collect_candidate()`。
- `tests/test_local_config.py`、`tests/test_real1688_adapter.py`、`tests/test_real_miaoshou_adapter.py`、`tests/test_browser_manager.py`、`tests/test_no_publish_guard.py`
  - 都以 `save_config()`/`load_config()` 驱动 JSON 主配置。

## 5. 关键重复和冲突结论

1. `mode` 与 `automation.mode` 语义冲突。
2. `dry_run_collect` 与 `collect_to_box_only` 语义需要拆分，不宜继续混用。
3. `chrome_debug_port` 与 `automation.cdp_port` 重复。
4. `chrome_profile_dir` 与 `automation.chrome_profile_dir` 重复。
5. `max_retry` 与 `image.retries`、`attempts` 语义重叠。
6. `data/config.json` 与 `settings` 表同时可影响配置，属于双源。
7. `automation.publish_recipe` 与 `no_publish` 安全边界高冲突，普通入口应隐藏。
8. `market.*` 与五国旧铺货需求强相关，应从首版普通入口移出。
9. `image.*` 大量字段属于高级配置，不应全部暴露给普通用户。
10. `image.api_key` 不能进入普通 JSON，必须继续走 Keychain/敏感存储。

## 6. 敏感配置位置

- `data/chrome-profile/`：登录态，不能进 Git，也不能泄露路径内容。
- `data/config.json`：可能包含真实关键词、路径和运行限制，不应提交。
- `workbench.token`：本地写接口保护，不应提交。
- macOS Keychain：`image-api-key`，不要写入普通 JSON 或日志。
- `automation.publish_recipe`：虽然不是秘密，但属于高风险配置，不应暴露在普通入口。
- `automation.chrome_path`、`automation.plugin_unpack_dir`、`automation.node_path`：本地环境细节，宜隐藏。

## 7. 模块1建议的统一路径

1. 以 `lib/local_config.py` 作为唯一“配置入口层”的主要实现。
2. `data/config.json` 作为普通用户的主配置。
3. `settings` 表只保留高级/兼容配置，先不删旧字段。
4. `POST /api/config` 负责基础配置保存与验证。
5. `POST /api/settings` 只保留高级配置兼容桥，后续逐步收口。
6. `app.py`、`lib/browser_manager.py`、`lib/real1688_adapter.py`、`lib/real_miaoshou_adapter.py` 应逐步只依赖统一配置读取函数。

## 8. 第3部分更新：配置优先级与兼容层

统一配置优先级已确定为：

1. 运行时系统检测结果；
2. 新版 `data/config.json`；
3. 环境变量中的敏感配置；
4. 旧版 `config.json` 迁移结果；
5. 旧 `settings` 表兼容值；
6. `DEFAULT_CONFIG`。

第3部分已建立兼容策略：

- 新配置是唯一真实来源；
- `settings` 表暂时作为旧业务兼容镜像；
- 新配置保存成功后同步必要 `automation.*` 字段；
- 正常启动时不会让 `settings` 反向覆盖新版配置；
- 旧平铺字段、未知字段、动作配方和五国旧规则保留到 `legacy` 或 settings 镜像；
- `publish`、`publish_enabled=true`、`no_publish=false` 不会生成发布模式。

新增文档：

- `docs/module-01/config-model.md`
- `docs/module-01/legacy-config-mapping.md`
- `docs/module-01/remaining-direct-config-reads.md`
