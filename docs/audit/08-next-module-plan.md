# 模块0审计：模块1计划

审计时间：2026-06-18

本阶段只做审计收尾与后续计划，不修改业务代码、数据库或页面。

模块1主题固定为：建立统一配置系统与最简配置结构。

## 1. 模块1目标

模块1只解决“配置从哪里来、如何校验、如何给主流程提供稳定输入”的问题，不改造完整自动化管线。

模块1应达到：

1. 建立唯一配置来源。
2. 将当前分散配置统一管理。
3. 区分普通配置、高级配置、系统自动检测配置。
4. 为后续 1688 找品、去重、筛选、标题图片处理、妙手采集提供稳定输入。
5. 保持 `no_publish=true`、`dry_run_collect=true`、`collect_to_box_only=true` 等安全默认值。
6. 不重做前端，不开发最终发布，不删除旧业务代码。

## 2. 模块1应修改的文件

| 文件 | 建议修改内容 | 原因 |
| --- | --- | --- |
| `lib/local_config.py` | 扩展为唯一配置入口；增加结构化默认值、类型校验、范围校验、兼容旧字段迁移 | 当前 `DEFAULT_CONFIG` 覆盖主流程安全与找品字段，但没有覆盖 settings 表中的图片、自动化、风险筛选等配置 |
| `data/config.example.json` | 更新为最简普通配置 + 高级配置的示例结构 | 当前示例只覆盖 `mode`、关键词、上限、启用开关、Chrome profile/port |
| `scripts/bootstrap.py` | 只在缺失时生成新结构配置；保留旧配置兼容 | 首次运行必须得到可用默认配置 |
| `app.py` | 只做配置 API 的薄层收口：`GET/POST /api/config`、启动时应用兼容字段、主流程读取入口替换为统一配置函数 | 当前 `workbench_config()` 与 `DB.settings()` 双源并存，部分值互相同步不完整 |
| `lib/database.py` | 原则上不改表结构；仅允许在必要时调整 settings seed 与配置迁移兼容读取 | 模块1不应做数据库重构；settings 表仍需兼容旧高级设置 |
| `static/app.js` | 仅允许最小调整配置读取/保存调用，避免普通配置继续写入多个入口 | 不重做页面，但要保证保存后的配置确实进入统一配置 |
| `static/index.html` | 原则上不重做；最多调整配置表单字段分组或隐藏明显高级字段入口 | 模块1不是页面收缩模块 |
| `tests/**` | 新增或补充配置读取、保存、默认值、校验、旧配置兼容测试 | 验收要求测试覆盖配置系统 |

## 3. 模块1原则上不应修改的文件

| 文件或目录 | 不修改原因 |
| --- | --- |
| `lib/real1688_adapter.py` | 模块1不改 1688 页面自动化逻辑；只让它后续从统一配置读取关键词、页数、数量限制 |
| `scripts/real1688_search.mjs` | 不改真实页面提取和 DOM 选择器 |
| `lib/real_miaoshou_adapter.py` | 不改妙手采集动作和采集箱确认逻辑；只保留配置读取兼容 |
| `scripts/cdp_runner.mjs` | 不改 CDP 动作执行器和配方行为 |
| `lib/image_inspector.py` | 不改图片下载和判断规则 |
| `lib/image_gateway.py` | 不改图片接口调用协议 |
| `lib/title_cleaner.py` | 不改标题清洗逻辑 |
| `static/styles.css` | 模块1不做视觉重构 |
| 数据库文件、日志、截图、Chrome profile | 运行时数据不得进入提交 |

## 4. 当前配置来源盘点

| 来源 | 文件或位置 | 当前用途 | 问题 |
| --- | --- | --- | --- |
| 本地 JSON 配置 | `lib/local_config.py`、`data/config.json`、`data/config.example.json` | `mode`、`dry_run_collect`、`collect_to_box_only`、`no_publish`、`max_items_per_run`、`max_pages_per_keyword`、`keywords`、主流程启用开关、`max_retry`、Chrome profile/port | 是当前最接近主流程的配置源，但字段过少，且与 settings 表存在重复 |
| settings 表 | `lib/database.py` `_seed_settings()`、`GET/POST /api/settings` | 图片接口、自动化路径、妙手/1688 地址、插件目录、动作配方、评估门槛、五国汇率运费 | 高级配置过多直接暴露在普通设置页；部分属于旧铺货/五国需求 |
| 前端设置表单 | `static/index.html`、`static/app.js` | 保存 `image.*`、`automation.*`、`evaluation.*`、`market.*` 到 `/api/settings` | 与 `/api/config` 分离，普通用户容易面对复杂字段 |
| 启动环境变量 | `app.py` `WORKBENCH_DATA_DIR`、`PORT` | 指定数据目录和端口 | 属系统/开发者配置，应自动或高级处理 |
| 代码写死默认值 | `lib/browser_manager.py`、`lib/real1688_adapter.py`、`lib/real_miaoshou_adapter.py`、`app.py` | Chrome/CDP 默认、1688 URL、妙手 URL、搜索页数/数量二次限制、图片和 CDP 超时 | 部分默认值与配置源重复，后续应由统一配置提供 |
| 安全门禁 | `lib/local_config.py`、`app.py`、`lib/real_miaoshou_adapter.py`、`lib/automation.py` | `no_publish`、危险发布文本拦截、写接口 token | 必须保留并优先于所有配置 |
| Keychain | `lib/keychain.py`、`POST /api/settings` | 图片 API Key | 正确做法是不写入 JSON/日志；模块1需保持敏感配置不落明文配置文件 |

## 5. 重复配置和命名冲突

| 配置含义 | 当前字段 | 冲突或重复 |
| --- | --- | --- |
| 运行模式 | `mode`、`automation.mode` | `mode` 在 JSON 中为 `real/mock`；`automation.mode` 在 settings 表中为 `dry_run/live`，语义不同但名称相近 |
| CDP 端口 | `chrome_debug_port`、`automation.cdp_port` | `apply_config_to_settings()` 只把 JSON 同步到 settings；前端保存 settings 后不一定回写 JSON |
| Chrome 用户目录 | `chrome_profile_dir`、`automation.chrome_profile_dir` | JSON 里有字段，settings 里由 `apply_config_to_settings()` 写入；前端设置页没有清晰呈现普通/高级边界 |
| 最大重试 | `max_retry`、`image.retries`、`automation_runs.attempts` 限制 | 总流程重试、图片重试和失败中心重试语义不统一 |
| 采集安全 | `dry_run_collect`、`collect_to_box_only`、`automation.mode`、批次 `dryRun` | 主流程采集箱安全与旧批次演练/真实发布混在页面和 API 中 |
| 价格/利润 | `evaluation.min_margin`、`market.target_margin_pct`、`market.*.shipping_cny`、`market.*.exchange` | 旧五国/铺货定价配置与新统一准入混合 |
| 图片处理 | `enable_image_check`、`image.base_url`、`image.path`、`image.model`、`image.timeout` | 是否检查图片是主流程配置，接口协议是高级配置 |
| 自动化地址 | `automation.alibaba_url`、`automation.miaoshou_url`、代码默认 URL | 地址应有默认值，普通用户不应频繁配置 |

## 6. 写死在代码中的配置

| 配置 | 当前位置 | 模块1建议 |
| --- | --- | --- |
| 每轮安全上限 10、每词页数 2 | `lib/local_config.py` `MAX_SAFE_ITEMS_PER_RUN`、`MAX_SAFE_PAGES_PER_KEYWORD` | 保留为安全硬上限；用户配置只能在范围内 |
| 1688 搜索页 URL 模板 | `lib/real1688_adapter.py` `search_url()` | 模块1不改实现，只记录为系统配置/内部常量 |
| Real1688Adapter 二次上限 50/10 | `normalize_limits()` | 后续模块统一为安全上限，避免 JSON 校验和适配器限制不一致 |
| CDP subprocess timeout | `extract()` 90 秒、`invoke_safe_recipe()` 180 秒、截图 20 秒 | 归入高级自动化配置，但模块1可先只定义结构 |
| 图片最少数量 3 | `analyze_candidate_precheck()` | 归入图片/筛选配置，默认值保留 3 |
| 价格带和重量带 | `sea_fit_status()` | 归入风险与筛选配置，模块5再细化规则 |
| 登录/验证码检测文本 | `lib/browser_manager.py` marker 常量 | 仅开发者可见或内部规则，不作为普通配置 |
| 危险发布动作正则 | `lib/local_config.py` `PUBLISH_ACTION_PATTERN` | 安全硬规则，不允许普通配置关闭 |

## 7. 只存在于前端或保存后未真正生效的配置

| 配置 | 位置 | 问题 |
| --- | --- | --- |
| `automation.publish_recipe` | 设置页和 settings 表 | 当前阶段禁止发布，普通入口应隐藏；即使保存也不应进入主流程 |
| 五国汇率和运费 | 设置页、settings 表、旧市场/批次逻辑 | 属旧五国/铺货需求，不应影响首版采集箱主流程 |
| `automation.mode` | 设置页、settings 表 | 与 JSON `mode` 不同；主 pipeline 的安全仍主要看 JSON `no_publish/dry_run_collect/collect_to_box_only` |
| 图片接口详细模板 | 设置页、settings 表 | 保存后可被 `image_gateway` 使用，但普通用户不应配置模板 |
| `image.concurrency` | settings 表和 `GENERATION_SLOTS` | 代码注释/界面提示“重启后生效”，保存后不会立即改变当前 semaphore |
| `automation.plugin_extension_id` | 设置页可保存 | 当前检测能力有限，是否真正影响插件采集需模块8确认 |
| 搜索关键词预设按钮 | `static/index.html` | 只填入手工关键词任务，不等同于 JSON `keywords` 主流程配置 |

## 8. 模块1目标配置结构建议

以下为文档建议，不在模块0创建代码。

### 8.1 基础任务配置

| 字段 | 类型/默认建议 | 来源或映射 | 用户层级 |
| --- | --- | --- | --- |
| `task.category` | string，默认空或“鞋类” | 当前 candidates/category、搜索关键词隐含类目 | 普通配置 |
| `task.keywords` | string[]，默认沿用 `keywords` | `data/config.json keywords` | 普通配置 |
| `task.target_collect_count` | int，默认 5，最大 10 | `max_items_per_run` 的业务目标口径 | 普通配置 |
| `task.max_candidates` | int，默认 10，最大 10 | `max_items_per_run` 安全上限 | 高级或系统限制 |
| `task.min_purchase_price` | number，默认 0 | 当前没有统一字段；可映射预检价格范围下限 | 普通配置 |
| `task.max_purchase_price` | number，默认 120 或空 | `sea_fit_status()` 当前价格带参考 | 普通配置 |
| `task.max_weight_g` | number，默认 2500 或 5000 | `sea_fit_status()`、`evaluation.py` | 普通配置 |
| `task.min_margin_pct` | number，默认 20 | `evaluation.min_margin` | 普通配置 |
| `task.auto_season_check` | bool，默认 true | `current_season_fit_status()` | 普通配置 |
| `task.process_images` | bool，默认 true | `enable_image_check` | 普通配置 |
| `task.mode` | enum `real`/`mock`，默认 `real` | JSON `mode` | 普通配置，但 mock 仅开发/演示 |

### 8.2 自动化配置

| 字段 | 类型/默认建议 | 来源或映射 | 用户层级 |
| --- | --- | --- | --- |
| `automation.max_pages_per_keyword` | int，默认 2，最大 2 | `max_pages_per_keyword` | 普通配置 |
| `automation.page_load_timeout_sec` | int，默认 90 | `real1688_search` subprocess timeout、CDP wait | 高级配置 |
| `automation.step_retry_limit` | int，默认 2，最大 5 | `max_retry`、`image.retries`、run attempts | 高级配置 |
| `automation.total_failure_limit` | int，默认 3 | 当前缺失 | 高级配置 |
| `automation.collect_interval_sec` | number，默认 1.2 或更高 | `Real1688Adapter.run_once()` sleep、妙手动作间隔 | 高级配置 |
| `automation.prefer_plugin` | bool，默认 true | 旧插件采集能力 | 高级配置 |
| `automation.enable_link_fallback` | bool，默认 true | `automation.link_collection_recipe` | 高级配置 |
| `automation.enable_dedupe` | bool，默认 true | `enable_dedupe` | 普通配置 |
| `automation.enable_risk_filter` | bool，默认 true | `enable_risk_filter` | 普通配置 |
| `automation.enable_title_clean` | bool，默认 true | `enable_title_clean` | 普通配置 |
| `automation.enable_miaoshou_collect` | bool，默认 true | `enable_miaoshou_collect` | 普通配置 |
| `safety.dry_run_collect` | bool，默认 true | `dry_run_collect` | 安全配置，不建议关闭 |
| `safety.collect_to_box_only` | bool，默认 true | `collect_to_box_only` | 安全配置，不建议关闭 |
| `safety.no_publish` | bool，固定默认 true | `no_publish` | 安全硬开关 |

### 8.3 环境配置

| 字段 | 类型/默认建议 | 来源或映射 | 用户层级 |
| --- | --- | --- | --- |
| `environment.chrome_path` | string，默认自动检测 | `automation.chrome_path`、`resolve_chrome_path()` | 系统自动检测，失败时高级 |
| `environment.chrome_profile_dir` | string，默认 `data/chrome-profile` | `chrome_profile_dir`、`automation.chrome_profile_dir` | 系统配置，普通隐藏 |
| `environment.cdp_port` | int，默认 9222 | `chrome_debug_port`、`automation.cdp_port` | 高级配置 |
| `environment.alibaba_url` | string，默认 `https://www.1688.com/` | `automation.alibaba_url` | 高级配置 |
| `environment.miaoshou_url` | string，默认 `https://erp.91miaoshou.com/` | `automation.miaoshou_url` | 高级配置 |
| `environment.plugin_extension_id` | string，默认空 | `automation.plugin_extension_id` | 高级配置 |
| `environment.plugin_unpack_dir` | string，默认空 | `automation.plugin_unpack_dir` | 高级配置 |
| `environment.database_path` | string，默认 `data/workbench.db` | `DATA_DIR / workbench.db` | 系统自动 |
| `environment.log_dir` | string，默认 `data/logs` | `ensure_local_runtime()` | 系统自动 |

### 8.4 图片配置

| 字段 | 类型/默认建议 | 来源或映射 | 用户层级 |
| --- | --- | --- | --- |
| `image.enable_check` | bool，默认 true | `enable_image_check` | 普通配置 |
| `image.min_width` | int，默认 600 或沿用当前规则 | `image_inspector` 尺寸判断 | 高级配置 |
| `image.min_height` | int，默认 600 或沿用当前规则 | `image_inspector` 尺寸判断 | 高级配置 |
| `image.min_count` | int，默认 3 | `analyze_candidate_precheck()` 图片数量门槛 | 普通配置 |
| `image.auto_process_unqualified` | bool，默认 false 或跟随接口可用性 | `auto_process_candidate_images()`、`image_gateway` | 普通配置 |
| `image.service.base_url` | string，默认空 | `image.base_url` | 高级配置 |
| `image.service.protocol` | enum，默认 `openai` | `image.protocol` | 高级配置 |
| `image.service.model` | string，默认 `gpt-image-1` | `image.model` | 高级配置 |
| `image.service.timeout_sec` | int，默认 120 | `image.timeout` | 高级配置 |
| `image.service.request_template` | object | `image.request_template` | 开发者配置 |

### 8.5 风险与筛选配置

| 字段 | 类型/默认建议 | 来源或映射 | 用户层级 |
| --- | --- | --- | --- |
| `risk.risk_terms` | string[] 或词库引用 | `RISK_KEYWORD_GROUPS` | 系统默认，高级维护 |
| `risk.brand_terms` | string[] 或词库引用 | `TitleCleaner`、风险词组 | 高级维护 |
| `risk.prohibited_rules` | rule[] | 当前风险词和 hard block 逻辑 | 高级维护 |
| `risk.min_sku_count` | int，默认 1 | `sku_complete` 当前布尔逻辑后续扩展 | 普通/高级 |
| `risk.supplier_requirements` | object | `supplier_name`、`shop_url`、`origin_place` | 普通/高级 |
| `dedupe.scope` | enum/list，默认 offer/url/title/image/box/local products | `dedupe_candidates()`、`collection_box_records` | 高级配置 |

## 9. 普通配置、高级配置、系统自动检测

### 普通用户配置

- 商品类目。
- 搜索关键词。
- 目标采集数量。
- 采购价格范围。
- 最大重量。
- 最低利润率。
- 是否自动判断季节。
- 是否处理图片。
- 运行模式。
- 是否开启去重、风险筛选、标题清洗、妙手采集。

### 高级配置

- CDP 端口。
- Chrome 路径。
- 1688/妙手地址。
- 妙手插件 ID 和插件目录。
- 页面加载超时。
- 单步骤重试次数。
- 采集间隔。
- 是否优先插件、是否启用链接兜底。
- 图片服务地址、路径、模型、请求模板、响应路径、轮询状态。
- 风险词库、品牌词库、禁限售规则。
- 自动化动作配方。

### 系统自动检测

- Chrome 是否存在。
- 专用 Chrome profile 是否存在。
- CDP 是否连接。
- 当前 1688 登录状态。
- 当前妙手登录状态。
- 是否出现验证码/短信/人机验证。
- 数据库路径。
- 日志、截图、图片目录。
- Workbench token。

## 10. 模块1验收标准

模块1完成后必须达到：

1. 所有主流程配置有唯一读取入口。
2. 配置有默认值。
3. 配置有类型校验。
4. 配置有范围校验。
5. 缺少配置时能给出明确错误。
6. 普通配置和高级配置分离。
7. 敏感信息不写入日志。
8. 旧配置能够兼容或迁移。
9. 配置保存后重新启动仍有效。
10. 测试覆盖配置读取、保存、校验和默认值。
11. 不破坏现有业务测试。
12. 不提前实现完整自动化管线。

## 11. 模块1禁止事项

- 不修改 1688 页面自动化逻辑。
- 不修改妙手采集逻辑。
- 不重做主页面。
- 不开发自动发布。
- 不删除旧业务代码。
- 不大规模重构 `app.py`。
- 不引入不必要的新框架。
- 不改变 `no_publish=true` 的默认安全边界。
- 不把 API Key、账号密码、cookie、Chrome profile 写入配置文件或日志。

## 12. 模块1建议执行顺序

1. 在 `lib/local_config.py` 中定义新配置 schema、默认值和兼容迁移函数。
2. 保持 `data/config.json` 可读旧字段，并在保存时输出新结构或兼容结构。
3. 让 `GET /api/config` 返回普通配置、高级配置、系统检测配置的分组视图。
4. 让 `POST /api/config` 做类型和范围校验，错误信息明确到字段。
5. 将 `apply_config_to_settings()` 收口为兼容桥，只同步仍由旧代码读取的必要字段。
6. 增加配置单元测试：默认值、旧字段迁移、非法类型、范围上限、安全开关、保存后重载。
7. 最后运行全量测试，确认旧 `/api/settings` 和已有业务测试未破坏。

## 13. 模块1明确不解决的问题

- 不解决真实 1688 搜索 DOM 稳定性。
- 不解决妙手采集箱回读确认。
- 不解决图片 OCR/视觉质检。
- 不解决统一 run_id 和断点续跑。
- 不解决页面收缩和普通入口隐藏。
- 不解决旧批次/发布流迁移。
- 不执行真实平台联调。

## 14. 本部分结论

模块1最小价值不是增加更多设置，而是减少配置来源：把 `data/config.json`、settings 表、前端设置表单、代码默认值之间的关系收口成一个清晰的读取入口。首版普通用户只应看到任务目标、关键词、数量、价格/重量/利润、季节、图片和安全模式；Chrome/CDP、插件、动作配方、图片接口模板、五国汇率运费和发布配方应进入高级或暂停范围。
