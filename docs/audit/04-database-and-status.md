# 模块0审计：数据库、状态与任务恢复

审计时间：2026-06-18

审计范围：SQLite 数据库结构、建表和迁移逻辑、状态字段和值、任务关联、幂等、重复执行、暂停/停止/恢复机制。

本阶段只做审计与文档整理，不修改业务代码、数据库结构、迁移或前端页面。

## 1. 数据库整体结构

当前项目使用单个 SQLite 数据库：

- 数据库文件：`data/workbench.db`，由 `app.py` 中 `DATA_DIR / "workbench.db"` 创建。
- 数据目录：默认 `data/`，可由 `WORKBENCH_DATA_DIR` 环境变量覆盖。
- 初始化入口：`app.py` 模块加载时实例化 `DB = Database(DATA_DIR / "workbench.db")`，`Database.__init__()` 调用 `initialize()`。
- 运行时初始化：`app.py initialize()` 调用 `ensure_local_runtime()`、`apply_config_to_settings()`、`DB.migrate_products_json()`，并重置部分运行中状态。
- 连接配置：`lib/database.py connect()` 开启 `PRAGMA foreign_keys = ON` 和 `PRAGMA journal_mode = WAL`。
- 迁移机制：没有版本号迁移表；当前使用 `CREATE TABLE IF NOT EXISTS` 加 `PRAGMA table_info()` 检测列，再执行 `ALTER TABLE ADD COLUMN` 的兼容式迁移。
- 唯一索引/约束：`candidates.source_url`、`evaluations(candidate_id, market)`、`market_versions(product_id, market)`、`shops(account_name, shop_name)`、`publish_keys.idempotency_key`，以及 `automation_logs(run_id, created_at DESC)` 索引。

当前主要数据表数量：16 张。

## 2. 主要数据表清单

| 表名 | 主要用途 | 主键 | 关系 | 关键字段 | 状态字段 | 创建位置 | 读取位置 | 更新位置 | 新主流程 | 重复职责/旧字段 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `candidates` | 1688 候选商品、去重、预检、标题、图片和采集前状态 | `id` | 被 `evaluations`、`products`、`collection_box_records`、`automation_runs`、`automation_logs` 引用 | `source_url`、`source_product_id`、`keyword`、`title`、`images`、`clean_title`、`local_images`、时间字段 | `status`、`dedupe_status`、`precheck_status`、`sea_fit_status`、`season_fit_status`、`image_status` | `lib/database.py initialize()` | `DB.get_candidate()`、`DB.list_candidates()`、大量 summary/API | `update_candidate()`、1688 保存、去重、预检、标题、图片、妙手采集 | 是 | `status` 是中文/英文混用的通用状态，和结构化状态列重复；五国评分相关字段偏旧 |
| `sourcing_runs` | 真实 1688 搜索运行记录 | `run_id` | pipeline context 和 automation_logs 通过 `sourcing_run_id` 关联 | `current_keyword`、`current_page`、`found_count`、`saved_count`、`skipped_count`、`failed_count` | `status` | `create_sourcing_run()` | `SOURCING.current()`、`automation_current_status()` | `update_sourcing_run()`、`Real1688Adapter` | 是 | 没有直接外键到 pipeline run，只在 pipeline context 保存 |
| `collection_box_records` | 已放入妙手采集箱/待处理区的本地记录 | `id` | 通过 `candidate_id`、`offer_id`、`source_url`、`run_id` 关联候选和采集 run | `candidate_id`、`offer_id`、`source_url`、`clean_title`、`images_used`、`collected_at` | `image_status`、`miaoshou_status` | `initialize()` | `list_collection_box_records()`、去重、统计 | `save_collection_box_record()` | 是 | 没有唯一约束防重复；没有妙手商品编号 |
| `title_cleaning_records` | 标题清洗历史 | `id` | `candidate_id` 或 `product_id` | `original_title`、`clean_title`、`removed_terms`、`risk_terms` | `status` | `initialize()` | `list_title_cleaning_records()` | `save_title_cleaning_record()` | 是 | 每次清洗都新增记录，可能重复记录同一结果 |
| `image_analysis_records` | 候选图片下载/分析历史 | `id` | `candidate_id` | `source_url`、`local_path`、`reasons`、`details`、`checked_at` | `status` | `initialize()` | `list_image_analysis_records()` | `save_image_analysis_record()` | 是 | 每次分析新增记录；无 run_id |
| `evaluations` | 五国评分结果 | `id` | `candidate_id` 外键到 candidates | `market`、各项 score、`confidence`、`hard_blocks`、`metrics` | 无通用 `status`，由 `evaluation_status()` 派生 | `initialize()` | `DB.get_candidate()`、候选 summary、五国达标池 | `save_evaluations()` | 旧流程为主 | 五国独立评分属于旧复杂工作台 |
| `products` | 正式商品/图片工厂/发布批次商品池 | `id` | `candidate_id` 外键；被 `market_versions`、`assets`、`generation_jobs` 使用 | `source_url`、`source_product_id`、`title`、`images`、`main_image` | `status` | `initialize()` | `list_products()`、批次、图片、workflow | `save_product()`、旧 collection、演示商品 | 部分 | 新主流程现阶段不应依赖正式商品池；状态偏旧 |
| `market_versions` | 五国版本、价格、库存、仓库、拦截原因 | `id` | `product_id` 外键；唯一 `product_id, market` | `market`、`language`、`sale_price`、`warehouse`、`inventory` | `blocked` | `initialize()`、`create_market_versions()` | 批次预检、市场弹窗 | `save_market_version()` | 否 | 店铺铺货和五国定价旧需求 |
| `shops` | 店铺配置 | `id` | 被批次和 publish key 使用 | `account_name`、`shop_name`、`market`、`warehouse` | `enabled` | `initialize()` | 批次预检、发布统计 | `POST /api/shops` | 否 | 店铺发布旧需求 |
| `assets` | 商品图片资产和人工审核结果 | `id` | `product_id` 外键 | `url`、`kind`、`prompt`、`rejection_reason` | `approved`、`review_status` | `initialize()` | 图片工厂、批次预检、失败中心 | 上传、生成完成、审核通过/驳回 | 部分 | 人工审核和正式商品图片工厂偏旧 |
| `generation_jobs` | AI 图片生成任务 | `id` | `product_id` 外键 | `preset`、`requested_count`、`completed_count`、`error`、`attempts`、`model`、`last_prompt`、`last_error` | `status` | `initialize()` | 图片工厂、失败中心、恢复 | `create_generation_job()`、`run_generation_job()`、`retry_generation_job()` | 部分 | 绑定 product，不直接绑定 candidate 或 pipeline |
| `batches` | 铺货批次 | `id` | `product_ids`、`shop_ids` JSON；被 publish runs、publish_keys 使用 | `name`、`dry_run`、`summary`、`confirmed_at` | `status` | `initialize()` | 铺货控制台、发布结果、workflow | `create_batch_from_payload()`、`confirm_batch()`、publish run | 否 | 店铺批次和发布旧需求 |
| `automation_runs` | 通用自动化运行表：pipeline、collection、keyword_search、publish | `id` | 可关联 `batch_id`、`candidate_id`；日志通过 `run_id` | `kind`、`current_step`、`steps`、`error`、`screenshot`、`diagnostics`、`attempts`、`resolution`、`context` | `status` | `initialize()`、`create_run()` | 运行列表、失败中心、workflow、pipeline | `update_run()`、各自动化函数 | 是 | 同一表混合新主流程和旧发布流，状态语义过载 |
| `automation_logs` | 自动化运行日志和失败详情 | `id` | `run_id`、`sourcing_run_id`、`candidate_id` | `product`、`keyword`、`current_step`、`message`、`error`、`screenshot`、`current_url`、`details` | `status`、`resolution` | `initialize()` | 日志 API、失败中心、统计 | `save_automation_log()`、`update_automation_log()` | 是 | 失败日志可被 retrying/handled，但不等于实体状态 |
| `settings` | SQLite 内部设置和高级配置 | `key` | 被各模块读取 | `value` JSON | 无 | `initialize()` seed | `setting()`、`settings()` | `set_settings()` | 部分 | 与 `data/config.json` 配置重复 |
| `publish_keys` | 发布幂等 key 和发布结果 | `idempotency_key` | `batch_id`、`product_id`、`shop_id` | `market`、`result`、`failure_reason`、`published_at` | `status` | `initialize()` | 批次预检、发布结果、workflow | `reserve_publish_keys()`、publish 完成、失败处理 | 否 | 最终发布旧需求 |

## 3. 表之间关系

```text
candidates
  -> evaluations(candidate_id)
  -> products(candidate_id)
  -> automation_runs(candidate_id, kind='collection')
  -> automation_logs(candidate_id)
  -> collection_box_records(candidate_id / offer_id / source_url)
  -> title_cleaning_records(candidate_id)
  -> image_analysis_records(candidate_id)

automation_runs(kind='pipeline')
  -> context.sourcingRunId -> sourcing_runs.run_id
  -> automation_logs.run_id

products
  -> market_versions(product_id)
  -> assets(product_id)
  -> generation_jobs(product_id)
  -> batches.product_ids(JSON)
  -> publish_keys.product_id

shops
  -> batches.shop_ids(JSON)
  -> publish_keys.shop_id

batches
  -> automation_runs(batch_id, kind='publish')
  -> publish_keys.batch_id
```

关系问题：

- 多数关系靠文本 ID 或 JSON 数组保存，只有 `evaluations`、`products`、`market_versions`、`assets`、`generation_jobs` 有显式外键。
- `collection_box_records` 没有外键和唯一索引，依赖应用层在 `validate_candidate()` 查询防重复。
- `sourcing_runs` 与 pipeline 运行没有数据库外键，靠 `automation_runs.context.sourcingRunId` 和 `automation_logs.sourcing_run_id` 关联。
- `image_analysis_records`、`title_cleaning_records` 没有 `run_id`，无法直接按一次 pipeline 运行汇总。

## 4. 状态字段和状态值

当前审计到的状态字段不少于 25 个，主要包括：

| 字段 | 所属表/对象 | 主要状态值 | 写入位置 | 读取位置 | 失败状态 | 可恢复性 | 卡住风险 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `automation_runs.status` | pipeline/collection/publish/keyword_search | `queued`、`running`、`starting`、`waiting_for_manual`、`completed`、`failed`、`blocked`、`stopped`、`waiting_browser`、`ready_for_live`、`awaiting_claim`、`waiting_confirmation`、`skipped` | `DB.create_run()`、`execute_pipeline_run()`、`automation_pause/resume/stop()`、`AutomationEngine`、`RealMiaoshouAdapter`、失败处理 | 运行列表、自动化控制台、失败中心、发布结果 | 有 | 部分，queued 可恢复，waiting 需人工 | 高，同一字段跨 kind 语义不同 |
| `sourcing_runs.status` | 1688 搜索 | `idle`、`starting_browser`、`checking_login`、`searching`、`extracting_results`、`saving_candidates`、`waiting_for_manual`、`completed`、`failed`、`stopped` | `Real1688Adapter.start_run/pause/resume/stop/run_once/extract()` | `/api/sourcing/current`、pipeline context | 有 | waiting 可 resume；active 重启后改 waiting | 中，CDP 子进程中途不能立即停 |
| `candidates.status` | 候选通用状态 | `待评估`、`已跳过`、`已达标`、`TikTok采集箱待优化`、`公用采集箱待认领`、`等待真实采集`、`人工处理`、`opening_miaoshou`、`waiting_for_manual`、`collecting_to_box`、`collect_failed`、`collected_to_box` | 候选批量操作、旧采集、RealMiaoshouAdapter、tests/selfcheck | 候选列表、workflow、collection queue | 有但不统一 | 依赖人工/重试 | 高，中文业务状态和英文流程状态混用 |
| `candidates.dedupe_status` | 候选去重 | `new_candidate`、`duplicate_offer_id`、`duplicate_url`、`duplicate_title`、`duplicate_image`、`already_collected_to_box`、`needs_manual_duplicate_check` | `dedupe_candidates()` | 候选 summary、过滤、Miaoshou validate | 重复/疑似重复即跳过 | 可重新跑去重 | 低 |
| `candidates.precheck_status` | 候选预检 | 空、`not_checked`、`precheck_passed`、`needs_title_clean`、`needs_image_check`、`low_priority_skipped`、`risk_blocked`、`precheck_failed` | `precheck_candidates()`、标题变化会清空 | 候选 summary、pipeline、Miaoshou validate | `risk_blocked`、`precheck_failed` | 部分可修复后重跑 | 中，空和 `not_checked` 同义 |
| `candidates.sea_fit_status` | SEA 适配 | `sea_fit_good`、`sea_fit_normal`、`sea_fit_poor` | `analyze_candidate_precheck()` | 候选 summary/precheck | poor 会低优先级 | 可重跑 | 低 |
| `candidates.season_fit_status` | 季节适配 | `season_fit_good`、`season_fit_normal`、`season_fit_poor` | `current_season_fit_status()` | 候选 summary/precheck | poor 会低优先级 | 随月份/规则重跑 | 低 |
| `candidates.image_status` | 候选图片 | `image_pending`、`original_usable`、`needs_cleanup`、`needs_generation`、`image_processing`、`image_ready`、`image_failed` | `update_candidate_image_result()`、图片字段变化重置 | pipeline、候选 summary、Miaoshou validate | `image_failed` | 可重新分析/处理 | 中，`original_usable` 与 `image_ready` 语义接近但准入只认 `image_ready` |
| `collection_box_records.miaoshou_status` | 采集箱记录 | `collected_to_box`、测试中也有中文如 `采集箱` | `save_collection_box_record()` | 列表、去重、统计 | 无规范失败值 | 不适用 | 中，状态值不完全规范 |
| `collection_box_records.image_status` | 采集时图片状态快照 | 通常 `image_ready` 或历史值 | `save_collection_box_record()` | 记录列表 | 无 | 不适用 | 低 |
| `title_cleaning_records.status` | 标题清洗记录 | `title_cleaned` | `save_title_cleaning_record()` | 清洗历史 | 无 | 不适用 | 低 |
| `image_analysis_records.status` | 图片分析记录 | `image_pending`、`original_usable`、`needs_cleanup`、`needs_generation`、`image_ready`、`image_failed` | `save_image_analysis_record()` | 图片分析历史 | 有 | 历史记录不可恢复 | 低 |
| `evaluations` 派生状态 | 五国评分 | `qualified`、`blocked`、`low_confidence`、`unqualified`、`missing` | `evaluation_status()` 派生 | 达标池、workflow | blocked/unqualified | 可重新评分 | 旧需求 |
| `products.status` | 正式商品 | `TikTok采集箱待优化`、`待图片审核` 等 | `save_product()`、旧 collection | 商品列表、workflow | 不统一 | 手工更新较多 | 中，非新主流程核心 |
| `market_versions.blocked` | 国家版本阻断 | bool | `create_market_versions()`、`save_market_version()` | 批次预检 | blocked | 可人工改但保留 hard block | 旧需求 |
| `shops.enabled` | 店铺启用 | bool | 店铺表单 | 批次预检 | disabled | 可编辑 | 旧需求 |
| `assets.approved` | 图片是否通过 | bool | 上传/审核/自检 | 图片工厂、批次预检 | false | 可审核 | 旧需求为主 |
| `assets.review_status` | 图片审核状态 | `pending`、`approved`、`rejected`、`skipped`、`handled`、`manual` | 审核 API、失败处理 | 图片工厂、失败中心 | rejected | 可处理 | 中，失败处理会写非审核语义 |
| `generation_jobs.status` | 生图任务 | `queued`、`preparing`、`running`、`awaiting_approval`、`completed`、`failed`、`skipped`、`handled`、`manual` | 生图创建/运行/重试/失败处理/恢复 | 图片工厂、失败中心 | failed | queued 可恢复，failed 可重试 | 中 |
| `batches.status` | 铺货批次 | `draft`、`preparing`、`confirmed`、`completed`、`completed_dry_run`、`failed`、`blocked`、`skipped`、`handled`、`manual` | 批次创建、prepare、confirm、publish run、失败处理 | 铺货控制台、发布结果 | failed/blocked | 旧流程重试 | 旧需求 |
| `publish_keys.status` | 发布幂等结果 | `reserved`、`published`、`dry_run`、`failed`、`blocked`、`duplicate`、`skipped`、`handled`、`manual` | `reserve_publish_keys()`、publish 完成、失败处理 | 批次预检、发布结果 | failed/blocked/duplicate | 手工处理 | 旧需求 |
| `automation_logs.status` | 运行日志条目 | `queued`、`running`、`completed`、`failed`、`blocked`、`skipped`、`waiting_for_manual` | `pipeline_log()` | 自动化日志/失败中心 | failed/blocked | 仅 resolution 处理 | 中，日志失败不等于实体失败 |
| `automation_logs.resolution` | 日志处理结果 | 空、`retrying`、`skipped`、`handled`、`manual` | 失败中心、retry failed | 失败中心 | 无 | 可改 | 低 |
| `automation_runs.resolution` | run 处理结果 | 空、`skipped`、`handled`、`manual` | 失败中心 | 失败中心 | 无 | 可改 | 低 |
| 浏览器平台 `status` | API 计算对象 | `ready`、`waiting_for_manual` | `BrowserManager.platform_status()` | `/api/browser/status`、`/api/platform/status`、pipeline env | waiting | 需人工 | 中 |
| 登录/验证布尔状态 | API 计算对象 | `alibaba_logged_in`、`miaoshou_logged_in`、`verification_required`、`waiting_for_manual` | `detect_*()` | 环境状态、pipeline env | verification/manual | 需人工 | 中，文本检测可能误判 |
| 插件状态 | 预检计算对象 | `pluginVerified`、`requiresCalibration` | `AutomationEngine.preflight()` | 设置/旧 automation preflight | 未验证/需校准 | 需人工配置 | 旧需求/部分采集 |

## 5. 状态冲突与假成功风险

### 5.1 状态冲突

1. `automation_runs.status='completed'` 含义不同。
   - pipeline completed 代表本地流程结束；collection completed 代表写入本地采集箱记录；publish completed 可能代表演练或真实发布完成。
   - 风险：聚合统计按 completed 计数时容易混淆新主流程和旧发布流。

2. `candidates.status` 混用中文业务状态和英文流程状态。
   - 例如 `待评估`、`已达标`、`TikTok采集箱待优化`、`opening_miaoshou`、`collected_to_box` 同字段共存。
   - 风险：前端、collection queue、workflow 可能把同一候选解释成不同阶段。

3. 候选预检有空字符串和 `not_checked` 两种未检查表达。
   - 数据库存空，summary/API 显示时转换为 `not_checked`。
   - 风险：筛选和查询接口需要重复兼容。

4. 图片状态 `original_usable` 和 `image_ready` 存在阶段重叠。
   - `lib/image_inspector.py` 单图可返回 `original_usable`，候选汇总最终满足条件时才写 `image_ready`。
   - 风险：如果中间状态被直接用于准入，可能误判原图可用但未满足数量。

5. `blocked` 同时表示安全拦截、风险阻断、批次阻塞、运行失败。
   - 不同对象的恢复方式不同。
   - 风险：失败中心统一展示时语义过宽。

6. `manual`/`waiting_for_manual`/`人工处理` 表达接近但分散在 run、log、candidate、asset、publish_key。
   - 风险：用户看到“人工处理”不一定知道应该恢复哪个实体。

7. `settings` 与 `data/config.json` 双配置源。
   - 例如 CDP port/profile 会从 config 写入 settings，但安全开关主要在 config。
   - 风险：配置显示、实际执行和高级设置可能不同步。

### 5.2 假成功风险

| 风险位置 | 证据 | 假成功表现 | 建议后续处理 |
| --- | --- | --- | --- |
| pipeline 结束 | `execute_pipeline_run()` 最后无论 `collectedToBox` 是否为 0，都会把 run 置为 `completed` | 没有商品进入妙手也显示“处理完成/完成” | completed 需区分 `completed_with_results`、`completed_no_items` 或至少结果态显著提示 |
| 妙手采集成功确认 | `RealMiaoshouAdapter.collect_candidate()` 在 runner ok 后写 `collection_box_records` | 本地显示已进入采集箱，但未回读妙手采集箱确认 | 模块8补真实回读或明确“本地已执行采集动作” |
| 旧 AutomationEngine collection | `_invoke_runner()` collection 成功后根据配方写 candidate collected 状态 | 插件/配方成功不一定等于采集箱内可见商品 | 收口到 RealMiaoshouAdapter 并保留诊断 |
| publish/dry run 统计 | `publish_keys.status='dry_run'` 被计入 success | 发布结果中心可能让用户误解为真实发布成功 | 当前阶段隐藏发布结果中心 |
| 批次进度条 | 前端按 `draft/preparing/其他` 显示 15/70/100 | 非真实完成状态也可能满进度 | 旧批次入口隐藏后降低影响 |
| 运行日志失败处理 | `automation_logs.resolution='handled'` 不改变候选/采集真实状态 | 用户可能以为失败商品已修复 | 失败处理需区分“已忽略”和“已真实恢复” |
| 图片审核/资产 | `approved=1` 和 `review_status` 兼容逻辑自动把 pending 视作 approved | 旧资产可能被视为审核通过 | 后续清理资产状态语义 |

## 6. 统一运行 ID 情况

结论：当前没有覆盖一次完整运行所有数据的统一运行 ID。

当前已有 ID：

- `automation_runs.id`：pipeline 主运行、collection run、publish run、keyword_search run 共用。
- `sourcing_runs.run_id`：真实 1688 搜索运行。
- `automation_runs.context.sourcingRunId`：pipeline 与 sourcing run 的弱关联。
- `automation_logs.run_id`：可关联 pipeline run 或其他 automation run。
- `automation_logs.sourcing_run_id`：可关联 sourcing run。
- `candidates.id`：候选商品。
- `products.id`：正式商品。
- `generation_jobs.id`：图片生成任务。
- `collection_box_records.run_id`：妙手采集 run。
- `batches.id`、`publish_keys.idempotency_key`：旧发布流。

逐项回答：

| 问题 | 结论 |
| --- | --- |
| 一次完整运行是否有唯一 ID | pipeline 有 `automation_runs.id`，但不是所有产物都强制写该 ID。 |
| 搜索结果是否能关联到这次运行 | 间接可通过 `automation_runs.context.sourcingRunId` 和 `automation_logs.sourcing_run_id` 关联；`candidates` 本身没有 `run_id`。 |
| 商品处理是否能关联到原始候选 | 可以，`products.candidate_id`、`automation_runs.candidate_id`、`collection_box_records.candidate_id` 存在。 |
| 图片任务是否能关联到商品 | `generation_jobs.product_id` 可关联商品；候选图片分析只有 `candidate_id`，没有 pipeline run。 |
| 妙手采集是否能关联到商品 | 可通过 `automation_runs.candidate_id`、`collection_box_records.candidate_id`、`offer_id` 关联候选；没有妙手商品编号。 |
| 错误是否能关联到具体步骤 | `automation_logs.current_step/status/error` 和 `automation_runs.diagnostics.failedStep` 可以定位；部分图片/标题记录无 run_id。 |
| 结果统计是否能准确按一次运行汇总 | 不能完全准确。`pipeline_counters()` 统计全库 candidates/collection records，而不是限定当前 run。 |
| 多次运行是否会互相污染 | 会。候选池、采集箱记录、失败统计是全局聚合，多次运行会影响当前 counters。 |
| 历史商品是否会重复进入新任务 | 有本地去重和 `collected_at` 排除，但缺少 run 级隔离和妙手端实时去重。 |

## 7. 幂等与重复执行检查

| 步骤 | 唯一键/前置检查 | 已完成识别 | 重复创建风险 | 重复调用妙手风险 | 安全重试 |
| --- | --- | --- | --- | --- | --- |
| 创建 pipeline run | `active_pipeline_run()` 阻止非 retry 的 active run | active 状态复用 | retry 会新建 run | 无 | 部分 |
| 创建 sourcing run | `Real1688Adapter.active_run()` 检查 active sourcing | active 状态复用 | waiting 状态不算 active，可新建 | 无 | 部分 |
| 1688 搜索 | 无页面级幂等，只按配置限制 | `sourcing_runs` 计数 | 可重复搜索同关键词 | 无 | 可重跑 |
| 保存候选 | `candidates.source_url UNIQUE`，保存时查 `source_url/source_product_id` | 已有候选复用 | 低，但 `source_product_id` 无唯一键 | 无 | 较安全 |
| 商品去重 | 更新 `candidates.dedupe_*` | `dedupe_checked_at`、状态 | 不新增记录 | 无 | 可重跑 |
| 商品筛选 | 更新 `precheck_*`，签名判断是否有效 | `precheck_checked_at`、`sourceSignature` | 不新增主记录 | 无 | 可重跑 |
| 标题清洗 | 更新 candidate，新增 history | `clean_title/title_cleaned_at` | 清洗记录会重复新增 | 无 | 可重跑 |
| 图片下载/分析 | 写 `data/images/{candidate_id}` 和 analysis history | `image_status/local_images` | image_analysis_records 会重复新增 | 无 | 可重跑 |
| 图片生成 | `generation_jobs.id`，active job set 防同 job 重复 | job status | 可对同 product 新建多个 job | 无 | failed job 可 retry，最多依赖调用逻辑 |
| 创建 collection run | `validate_candidate()` 查 product/collection_box_records | 已采集候选阻断 | 并发下可创建多个 run | 有 | 部分 |
| 提交妙手采集 | 配方执行前校验 no_publish 和候选准入 | 采集后写 `collection_box_records` | 并发写入前存在窗口 | 有，特别是多标签页/多入口 | 需加强候选级锁 |
| 保存采集成功结果 | `collection_box_records.id` 主键，非 candidate/offer 唯一 | validate 前查已有记录 | 可重复保存不同 id | 间接导致重复 | 部分 |
| 自动重试 | run attempts 限制 2；automation_retry_failed 新建 pipeline | attempts/resolution | 可能多次新建 retry pipeline | 可能重复采集未写成功记录的商品 | 部分 |
| 程序恢复 | queued run 自动 enqueue；running/preparing 改 queued | 候选状态跳过已处理 | 可能重复执行页面动作级步骤 | 有 | 候选级恢复，不是动作级 |

## 8. 暂停、停止和恢复能力

| 问题 | 当前真实机制 |
| --- | --- |
| 1. 暂停按钮修改了什么 | `automation_pause()` 写 pipeline context `requestedPause=True`，调用 `SOURCING.pause()`，把 run status 改为 `waiting_for_manual`，写日志。 |
| 2. 后台任务何时检查暂停状态 | pipeline 在搜索轮询循环和候选处理循环边界调用 `pipeline_should_pause()`；Real1688Adapter 在每页前检查 sourcing run status。 |
| 3. 暂停后浏览器操作是否立刻停止 | 不会。已经启动的 CDP/Node subprocess 不会被强制中断，只在返回后生效。 |
| 4. 继续后从哪里恢复 | `automation_resume()` 把 run 改为 `queued` 并重新 enqueue。pipeline 会重新进入 `execute_pipeline_run()`；若不是 retry_failed，会可能重新开始 sourcing；候选处理按当前候选状态跳过部分已处理项。 |
| 5. 停止是软停止还是强制终止 | 软停止。写 `requestedStop=True`，调用 `SOURCING.stop()`，状态设为 `stopped`；不强杀正在执行的 CDP 子进程。 |
| 6. 停止后是否保存当前进度 | 保存 pipeline context、sourcing current page/keyword 和候选状态，但不是动作级浏览器断点。 |
| 7. 程序崩溃后是否能恢复 | `initialize()` 把 running/preparing automation runs 改 queued；`recover_background_jobs()` enqueue queued runs；active sourcing 改 `waiting_for_manual`。 |
| 8. 电脑重启后是否能恢复 | 与程序崩溃类似，前提是数据库保留；Chrome/CDP 和登录态需重新检测。 |
| 9. 恢复时是否跳过已完成步骤 | 候选级会跳过重复、已 collected_at、部分状态已完成项；但搜索和页面动作级步骤不保证跳过。 |
| 10. 恢复时是否可能重复采集 | 可能。若外部妙手已采集成功但本地未写 `collection_box_records`，恢复/重试会再次调用采集。 |
| 11. 连续失败后状态如何处理 | automation_run retry attempts 达 2 后失败中心不允许继续 retry；generation job 有 attempts 字段；pipeline retry_failed 没有统一最大次数。 |
| 12. 是否存在最大重试次数 | `resolve_failure_task()` 对 automation_run 限制 attempts < 2；generation_jobs 有 attempts 字段；pipeline retry failed 不同机制，未统一。 |

结论：当前支持“软暂停/软停止”和“候选级恢复”，不支持真实安全断点续跑。

## 9. 最严重的状态问题

1. 没有统一 run_id 贯穿候选、图片分析、标题记录、采集记录和统计。
   - 结果：`pipeline_counters()` 用全库聚合，不能准确表示一次运行结果。

2. pipeline 可完成但无采集成功。
   - 结果：run status 为 `completed`，但 `collectedToBox` 可能为 0，用户会误以为本次真实闭环成功。

3. 妙手采集成功以本地 runner ok 和写库为准。
   - 结果：外部妙手采集箱未回读确认，可能出现“商品显示成功但妙手未确认”。

4. `automation_runs.status` 和 `candidates.status` 语义过载。
   - 结果：同一状态值跨不同 kind 意义不同；候选通用状态混杂中文业务状态和英文流程状态。

5. 重启恢复不是动作级断点续跑。
   - 结果：恢复可能重复搜索、重复候选处理，极端情况下重复采集。

## 10. 后续状态机改造建议

本模块只写建议，不修改数据库。

1. 后续状态机/结果统计模块建议增加统一 `pipeline_run_id`。
   - 新主流程下 candidates、title records、image records、collection records、automation logs 都应能按一次点击运行汇总。
   - 模块1主题已收缩为统一配置系统，不应在模块1内创建数据库迁移；最多在配置命名中预留运行统计所需字段。

2. 为 `collection_box_records` 增加幂等约束。
   - 建议后续至少对 `candidate_id`、`offer_id` 或标准化 `source_url` 建唯一约束或应用层事务锁。

3. 把 `automation_runs.status` 按 kind 定义状态机。
   - pipeline、sourcing、collection、publish 不应共用一套松散状态解释。

4. 把 `candidates.status` 降级为展示字段或废弃。
   - 主判断应来自 `dedupe_status`、`precheck_status`、`image_status`、`collected_at/collection_box_records`。

5. 区分完成类型。
   - pipeline 建议区分 `completed_with_results`、`completed_no_items`、`completed_with_failures`，避免假成功。

6. 恢复机制从“重跑线程”改为“步骤级 checkpoint”。
   - 每个候选记录最后完成步骤；恢复时只从未完成步骤继续，外部动作前做幂等检查。

7. 真实妙手采集成功需要外部确认。
   - 如果无法回读采集箱，也应把状态命名为 `collection_action_executed`，不要直接等同 `collected_to_box`。

8. 发布/批次旧表可保留但从新主流程统计中排除。
   - `batches`、`publish_keys`、`market_versions`、`shops` 属旧发布需求，后续普通入口隐藏后仍可保留历史数据。

## 11. 本部分明确结论

- 当前是否有统一运行ID：没有。pipeline 有 `automation_runs.id`，但 candidates、title records、image records、collection records 不都强制保存该 ID。
- 当前能否准确统计一次运行结果：不能完全准确。当前自动化 counters 多数按全库 candidates/collection records 聚合，会受历史数据污染。
- 当前是否支持安全断点续跑：不支持真正安全断点续跑。当前是软恢复和候选级跳过，不是浏览器动作级 checkpoint。
- 当前是否可能重复采集同一商品：可能。应用层有去重和 collection record 检查，但 `collection_box_records` 无唯一约束，外部成功本地失败、多标签页并发或重试都可能重复调用妙手。
- 当前暂停和停止是否真实有效：部分有效。它们能改变本地状态并在循环边界生效，但不能立刻停止正在执行的 CDP/Node 浏览器动作。
- 当前最严重的状态冲突是什么：`automation_runs.status` 和 `candidates.status` 语义过载，加上 pipeline completed 不代表采集成功，造成假成功和统计不准。
- 哪些数据表可以保留：`candidates`、`sourcing_runs`、`collection_box_records`、`title_cleaning_records`、`image_analysis_records`、`automation_runs`、`automation_logs`、`settings`、部分 `assets/generation_jobs`。
- 哪些数据表属于旧需求：`evaluations`、`products`、`market_versions`、`shops`、`batches`、`publish_keys`，以及旧图片人工审核相关 `assets` 用法。
- 模块1是否需要修改数据库：原则上不需要修改数据库结构。统一运行 ID、采集记录幂等约束、运行结果状态语义和新主流程统计隔离应放到后续状态机/结果统计模块；模块1只处理配置来源、默认值、校验和旧配置兼容。
