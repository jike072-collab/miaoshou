# 模块0审计：当前真实流程与调用链

审计时间：2026-06-18

审计范围：前端入口、后端 API、任务编排、1688 搜索、候选处理、图片处理、妙手采集、暂停/继续/停止、失败重试、模拟入口和重复执行风险。

本阶段只做审计与文档整理，不修改业务代码。

## 1. 当前真实入口

当前最接近新定位的一键入口是首页第一屏自动化控制台：

前端按钮：`static/index.html` 中 `#automation-start`，按钮文案为“开始自动找品采集”。

前端事件：`static/app.js` 中 `$("#automation-start").addEventListener("click", () => automationAction("start", "自动找品采集已启动"))`。

调用 API：`POST /api/automation/start`。

后端接收：`app.py` 的 `route_post()` 分发到 `automation_start()`。

后端任务创建：`automation_start()` 调用 `create_pipeline_run()`，写入 `automation_runs.kind='pipeline'`，再调用 `enqueue_pipeline_run(run["id"])`。

后台执行：`enqueue_pipeline_run()` 后进入 `execute_pipeline_run(run_id)`。

状态轮询：前端启动后通过 `refreshAutomationConsole()` 和 `pollRuntime()` 轮询 `GET /api/automation/current`、`GET /api/automation/logs`、`GET /api/automation/failures`。

结论：这是当前唯一明确串联“1688 搜索 -> 去重 -> 风险预检 -> 标题清洗 -> 图片检查 -> 妙手采集箱”的主流程入口。

## 2. 当前真实调用链

### 2.1 一键主流程链路

```text
首页“开始自动找品采集”
-> static/app.js automationAction("start")
-> POST /api/automation/start
-> app.py automation_start()
-> create_pipeline_run()
-> automation_runs(kind='pipeline')
-> enqueue_pipeline_run()
-> execute_pipeline_run(run_id)
-> assert_real_pipeline_safety()
-> real_pipeline_environment_status()
-> SOURCING.start_run()
-> sourcing_runs
-> enqueue_sourcing_run()
-> execute_sourcing_run()
-> Real1688Adapter.run_once()
-> scripts/real1688_search.mjs
-> candidates
-> pipeline_process_candidates()
-> dedupe_candidates()
-> precheck_candidates()
-> clean_titles_for_candidates()
-> auto_process_candidate_images()
-> MIAOSHOU.collect_ready()
-> RealMiaoshouAdapter.collect_candidate()
-> scripts/cdp_runner.mjs
-> collection_box_records
-> automation_logs / automation_runs
```

### 2.2 调用链逐项回答

| 问题 | 当前代码证据与结论 |
| --- | --- |
| 1. 用户从哪里创建任务 | 首页第一屏自动化控制台，`static/index.html` 的“开始自动找品采集”。另有候选导入、真实找品、关键词任务、批次发布等旧入口，但新主流程入口是自动化控制台。 |
| 2. 哪个前端按钮触发 | `#automation-start`。 |
| 3. 调用了哪个 API | `POST /api/automation/start`。 |
| 4. 后端由哪个函数接收 | `app.py` 的 `route_post()` 分发到 `automation_start()`。 |
| 5. 创建了什么任务记录 | `create_pipeline_run()` 创建 `automation_runs.kind='pipeline'`。1688 搜索阶段另创建 `sourcing_runs`。妙手采集阶段每个候选会创建 `automation_runs.kind='collection'`。 |
| 6. 任务保存到哪个数据表 | 主任务在 `automation_runs`，运行日志在 `automation_logs`，1688 搜索在 `sourcing_runs`，采集箱结果在 `collection_box_records`。 |
| 7. 任务如何进入1688搜索 | `execute_pipeline_run()` 在环境检查通过后调用 `SOURCING.start_run()`，再 `enqueue_sourcing_run()`，进入 `Real1688Adapter.run_once()`。 |
| 8. 搜索结果保存在哪里 | `Real1688Adapter.save_results()` 写入 `candidates`，并更新标题、价格、图片、供应商、页码、排名等字段。 |
| 9. 商品怎样进入去重 | 搜索完成后 `execute_pipeline_run()` 调用 `pipeline_process_candidates()`；每个候选先进入 `dedupe_candidates([candidate_id])`。 |
| 10. 去重后怎样进入筛选 | 非重复候选继续调用 `precheck_candidates([candidate_id])`。重复候选写入日志后跳过。 |
| 11. 筛选后怎样进入标题处理 | 预检未风险阻断、未低优先级跳过，且缺少 `clean_title` 或需要清洗时，调用 `clean_titles_for_candidates([candidate_id])`。 |
| 12. 标题处理后怎样进入图片处理 | 标题清洗后再次执行 `precheck_candidates()`，通过后调用 `auto_process_candidate_images([candidate_id])`。 |
| 13. 图片处理后怎样进入妙手采集 | 候选 `image_status == image_ready` 后调用 `MIAOSHOU.collect_ready([candidate_id])`。图片未就绪则记录失败并跳过该候选。 |
| 14. 如何确认采集成功 | `RealMiaoshouAdapter.collect_candidate()` 执行安全采集配方成功后写入 `collection_box_records`，并把候选状态更新为 `collected_to_box`。当前未发现回读妙手采集箱列表确认的代码。 |
| 15. 失败后如何重试 | 首页“重试失败”调用 `POST /api/automation/retry-failed`，创建新的 pipeline run 并设置 `retry_failed=True`；失败中心也有 `POST /api/failures/action` 和旧 `POST /api/runs/:id/retry`。 |
| 16. 暂停、继续、停止如何生效 | `/api/automation/pause|resume|stop` 更新 `automation_runs.context` 的 `requestedPause/requestedStop`，并调用 `SOURCING.pause()/stop()`；流程在搜索轮询和候选循环边界检查。CDP 子进程执行中不能立即中断。 |
| 17. 程序重启后是否恢复 | `initialize()` 会把 running/preparing 的 `automation_runs` 改回 queued；`recover_background_jobs()` 会重新排队 queued 的 `automation_runs` 和 `generation_jobs`，并把 active `sourcing_runs` 改为 `waiting_for_manual`。不是页面动作级断点恢复。 |
| 18. 哪些步骤必须人工点击 | 首次启动/登录专用 Chrome、处理验证码/短信/人机验证、配置妙手安全采集配方、处理失败任务；旧入口中还有大量手工去重、预检、标题、图片、批次和发布操作。 |
| 19. 哪些步骤没有自动进入下一步 | 图片不达标时不会进入妙手；妙手安全配方未配置时不会自动采集；登录/验证码会等待人工；旧五国评分/批次/发布不属于新主流程自动下一步。 |
| 20. 哪些能力虽然存在但没有接入主流程 | 五国版本/定价、店铺批次、最终发布确认、图片人工审核、文本本地化、妙手商品编号回写、配置备份、数据库备份、真实回读妙手采集箱去重。 |

## 3. 每一步状态变化

| 主步骤 | 代码位置 | 主要数据表 | 状态变化 | 下一步 |
| --- | --- | --- | --- | --- |
| 搜索 | `execute_pipeline_run()`、`Real1688Adapter.run_once()` | `automation_runs`、`sourcing_runs` | pipeline run: `running`；sourcing run: `checking_login/searching/extracting_results/saving_candidates/completed` | 保存候选 |
| 保存候选 | `Real1688Adapter.save_results()` | `candidates`、`sourcing_runs` | 新候选写入或更新，`saved_count/skipped_count/failed_count` 变化 | 去重 |
| 去重 | `pipeline_process_candidates()`、`dedupe_candidates()` | `candidates`、`collection_box_records`、`products`、`automation_runs` | `dedupe_status` 更新为 `new_candidate` 或重复状态；重复写日志并跳过 | 风险预检 |
| 风险预检 | `precheck_candidates()`、`analyze_candidate_precheck()` | `candidates` | `precheck_status` 为 `precheck_passed/risk_blocked/low_priority_skipped/precheck_failed/needs_*` | 标题清洗或跳过 |
| 标题清洗 | `clean_titles_for_candidates()`、`TitleCleaner.clean()` | `candidates`、`title_cleaning_records` | 写入 `clean_title`、`removed_terms`、`risk_terms` | 复查预检 |
| 图片检查 | `auto_process_candidate_images()`、`analyze_candidate_images_for_ids()` | `candidates`、`image_analysis_records`、`data/images` | `image_status` 为 `image_ready/needs_generation/image_failed` 等 | 妙手采集或跳过 |
| 妙手采集 | `MIAOSHOU.collect_ready()`、`RealMiaoshouAdapter.collect_candidate()` | `automation_runs`、`collection_box_records`、`candidates` | collection run: `running/completed/blocked/waiting_for_manual`；candidate: `opening_miaoshou/collecting_to_box/collected_to_box/collect_failed` | 进入采集箱记录 |
| 进入采集箱 | `save_collection_box_record()` | `collection_box_records`、`candidates` | 写入 `miaoshou_status='collected_to_box'`，候选 `status='collected_to_box'` | 结果统计 |

## 4. 当前流程中断位置

1. 【流程中断】Chrome/CDP 未就绪。
   - 证据：`execute_pipeline_run()` 检查 `env["chromeReady"]` 和 `env["cdpReady"]`，不通过时把 pipeline run 置为 `waiting_for_manual`。
   - 原因：需要专用 Chrome 运行并连接 CDP。
   - 后续模块：环境启动与检测模块。

2. 【流程中断】1688 或妙手未登录，或出现验证码/短信/人机验证。
   - 证据：`execute_pipeline_run()` 检查 `alibabaLoggedIn`、`miaoshouLoggedIn`、`verificationRequired`；`Real1688Adapter.ensure_alibaba_ready()` 和 `RealMiaoshouAdapter.ensure_miaoshou_ready()` 也会返回等待人工。
   - 原因：项目明确禁止绕过平台安全机制。
   - 后续模块：环境检测和人工恢复体验。

3. 【流程中断】1688 搜索执行失败。
   - 证据：`Real1688Adapter.extract()` 调用 `scripts/real1688_search.mjs`，失败会将 `sourcing_runs.status` 置为 `failed`；pipeline 随后置为 `failed`。
   - 原因：真实页面 DOM、网络、登录态或脚本执行失败。
   - 后续模块：1688 搜索稳定性和诊断。

4. 【流程中断】单个候选图片不达标。
   - 证据：`pipeline_process_candidates()` 中 `not summary.get("imageReady")` 时写失败日志并 `continue`。
   - 原因：当前图片不合格不会进入妙手采集箱。
   - 影响：不中断整批，但该商品链路中断。
   - 后续模块：图片处理队列和自动生成/清洗。

5. 【流程中断】妙手安全采集配方未配置。
   - 证据：`RealMiaoshouAdapter.collect_candidate()` 中 `if not recipe` 则 `waiting_for_manual`，错误为“妙手采集箱安全配方未配置”。
   - 原因：没有默认真实妙手采集箱操作配方。
   - 后续模块：真实妙手采集箱接入。

6. 【流程中断】妙手页面出现发布/上架/提交类危险按钮。
   - 证据：`detect_dangerous_texts()` 命中后 `RealMiaoshouAdapter.collect_candidate()` 置为 `waiting_for_manual`。
   - 原因：`no_publish=true` 安全边界要求默认不点击危险动作。
   - 后续模块：安全采集入口识别和页面隔离。

7. 【流程中断】任务最终可显示 `completed` 但没有任何商品进入采集箱。
   - 证据：`execute_pipeline_run()` 结束时若 `counters["collectedToBox"]` 为 0，`current_step` 为“处理完成”并仍把 run 状态置为 `completed`。
   - 原因：所有商品可能被重复、风险、图片或妙手准入拦截。
   - 风险：用户可能误解为真实闭环成功。
   - 后续模块：结果语义和失败统计。

## 5. 人工操作位置

| # | 人工操作 | 入口位置 | 对应代码 | 是否阻塞自动流程 | 建议处理方式 | 后续模块 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 启动专用 Chrome | 环境状态“启动浏览器” | `POST /api/browser/start`、`BrowserManager.start()` | 是 | 保留并做成自动环境检查动作 | 模块1/2 |
| 2 | 首次登录 1688 | 专用 Chrome 页面 | `detect_alibaba_login()` | 是 | 保留人工登录，不保存账号密码 | 模块2 |
| 3 | 首次登录妙手 | 专用 Chrome 页面 | `detect_miaoshou_login()` | 是 | 保留人工登录，不保存账号密码 | 模块2/8 |
| 4 | 处理验证码/短信/人机验证 | 专用 Chrome 页面 | `detect_verification()` | 是 | 保留人工处理，页面给明确恢复入口 | 模块2 |
| 5 | 配置关键词 | 配置文件或设置 | `data/config.json`、`POST /api/config` | 是，若为空 | 简化为首次配置 | 模块1/9 |
| 6 | 手工输入 1688 链接 | 候选区“导入待评估候选” | `POST /api/candidates/import-links` | 不应是主流程 | 隐藏普通入口，保留高级补录 | 模块后续收缩 |
| 7 | 手工创建关键词任务 | 候选区“创建找品任务” | `POST /api/candidates/search` | 不应是主流程 | 隐藏或改造成主配置 | 模块后续收缩 |
| 8 | 手工启动真实找品 | 选品雷达“开始真实找品” | `POST /api/sourcing/start` | 与主流程重复 | 保留底层能力，隐藏普通入口 | 模块9 |
| 9 | 手工选择候选商品 | 候选表 checkbox | `selectedCandidates()` | 不应阻塞主流程 | 只作为异常处理 | 模块9 |
| 10 | 手工点击去重 | `#dedupe-candidates` | `POST /api/candidates/dedupe` | 主流程已自动做 | 隐藏普通入口，保留高级修复 | 模块9 |
| 11 | 手工点击预检 | `#precheck-candidates` | `POST /api/candidates/precheck` | 主流程已自动做 | 隐藏普通入口，保留高级修复 | 模块9 |
| 12 | 手工补供应/市场数据 | 候选弹窗 | `POST /api/candidates/:id`、`POST /api/candidates/evaluate` | 旧五国流程会阻塞 | 改造成自动采集字段和异常补录 | 模块5 |
| 13 | 手工进入五国评分 | `#evaluate-selected` | `POST /api/candidates/evaluate` | 旧流程 | 隐藏普通入口 | 模块5 |
| 14 | 手工清洗标题 | `#clean-title-candidates` | `POST /api/products/clean-title` | 主流程已自动做 | 保留高级修复 | 模块6/9 |
| 15 | 手工下载图片 | `#download-images` | `POST /api/images/download` | 主流程已自动做 | 保留高级修复 | 模块7 |
| 16 | 手工分析图片 | `#analyze-images` | `POST /api/images/analyze` | 主流程已自动做 | 保留高级修复 | 模块7 |
| 17 | 手工自动处理图片 | `#auto-process-images` | `POST /api/images/auto-process` | 主流程已自动做基础处理 | 保留异常处理 | 模块7 |
| 18 | 手工发起妙手采集 | `#collect-qualified`、达标池采集按钮 | `POST /api/miaoshou/collect-ready` | 与主流程重复 | 隐藏普通入口，保留失败重试 | 模块8/9 |
| 19 | 手工确认采集失败处理 | 采集任务详情 | `POST /api/collections/bulk-action` | 失败恢复需要 | 保留为失败处理中心 | 模块9 |
| 20 | 手工审核图片 | 图片工厂通过/驳回 | `POST /api/images/:id/approve|reject` | 新主流程不应正常依赖 | 隐藏普通入口，保留异常审核 | 模块7 |
| 21 | 手工创建演示商品 | 商品空态按钮 | `POST /api/products` | 不属于真实流程 | 隔离到演示/测试 | 后续收缩 |
| 22 | 手工配置店铺 | 铺货控制台店铺表单 | `POST /api/shops` | 新阶段不需要 | 移入高级或暂停 | 后续收缩 |
| 23 | 手工创建铺货批次 | 铺货批次表单 | `POST /api/batches/create` | 新阶段禁止进入发布链路 | 隐藏或暂停 | 后续收缩 |
| 24 | 手工强确认最终发布 | 批次强确认弹窗 | `POST /api/batches/:id/confirm` | 禁止进入 | 隐藏入口，保留安全拦截 | 后续收缩 |
| 25 | 手工配置 CDP/妙手动作配方 | 设置页自动化设置 | `POST /api/settings` | 妙手真实采集前需要 | 移入高级设置，普通流程只提示必需项 | 模块8 |
| 26 | 手工运行自检/修复 | 设置页自检按钮 | `POST /api/selfcheck`、`POST /api/selfcheck/repair` | 非主流程 | 保留高级诊断 | 模块9 |

结论：当前可见人工操作至少 26 类。其中 1-5 属于安全和首次配置所需；其余大多来自旧复杂工作台，应该从普通主流程移出。

## 6. 模拟或演示位置

| 模拟/演示位置 | 文件位置 | 触发条件 | 是否出现在正式页面 | 是否可能误导真实成功 | 是否污染数据库 | 建议 |
| --- | --- | --- | --- | --- | --- | --- |
| 从达标候选创建演示商品 | `static/index.html`、`static/app.js` | 商品空态点击“从达标候选创建演示商品” | 是 | 是，会提示“演示商品已创建” | 是，调用 `POST /api/products` 写入 `products` | 隔离到演示模式或隐藏普通入口 |
| 工作流演示种子 | `scripts/seed_workflow_demo.py` | 手工运行脚本 | 否，脚本不自动运行 | 中，若写入默认 DB 会显示演示批次/商品 | 是，写入 candidates/products/assets/shops/batches/runs | 保留给测试/演示，但必须使用临时数据目录 |
| 自检 mock 图片中转站和假 1688 URL | `scripts/selfcheck.py` | 运行 selfcheck | 否 | 低，主要是测试；但不能代表真实平台 | 使用临时目录时不污染，若改配置有风险 | 保留为自检，文档注明非真实平台 |
| 单元测试 mock/fake | `tests/**` | 运行测试 | 否 | 低 | 使用测试 DB/临时对象 | 保留测试，不作为真实闭环证据 |
| 批次列表本地进度条 | `static/app.js` | 渲染批次列表 | 是 | 中，`draft/preparing/其他` 显示 15/70/100 | 否 | 旧发布流隐藏后影响降低 |
| 发布结果统计 | `app.py`、`static/app.js` | 读取 `publish_keys` | 是 | 中，本地 `dry_run/published` 状态可能被误读为真实平台结果 | 是，来自本地 DB | 当前阶段隐藏发布区或明确标注禁用 |

## 7. 尚未串联或真实性不足的能力

| 能力 | 当前状态 | 中断原因 | 后续处理 |
| --- | --- | --- | --- |
| 妙手采集箱真实回读确认 | 采集成功后写本地 `collection_box_records` | 未发现查询妙手采集箱列表并匹配商品的实现 | 模块8补真实确认策略 |
| 妙手已有商品实时去重 | 主要查本地 `products` 和 `collection_box_records` | 未见实时查妙手端已有采集/商品 | 模块4或模块8补充 |
| 图片 OCR/视觉质检 | 基础规则可运行 | 无 OCR/视觉模型，无法可靠识别图中文字/水印/二维码 | 模块7明确能力边界或接入真实检测 |
| 图片不合格后的自动生成/清洗 | 有图片生成接口 | 依赖外部中转站和配置，不是默认闭环 | 模块7/后续图片处理 |
| 程序重启后的精确断点续跑 | 有 queued run 恢复和候选级跳过 | 不能恢复 CDP 页面动作级位置 | 模块9完善恢复语义 |
| 五国评分到新 SEA 简化准入 | 五国评分存在 | 过于复杂且依赖人工市场数据 | 模块5改造成自动筛选参考或隐藏 |
| 店铺批次与发布 | 代码完整 | 新阶段明确不做最终发布 | 从主流程移出 |

## 8. 重复入口和重复执行风险

| 入口 | 页面位置/按钮 | API | 控制对象 | 重复风险 |
| --- | --- | --- | --- | --- |
| 一键自动化 | 首页“开始自动找品采集” | `POST /api/automation/start` | pipeline run | 主入口。前端会禁用 active 状态，但多标签页仍可并发 POST；后端有 `ACTIVE_PIPELINE_RUNS` 防同 run 重复，未见全局“同一时间只允许一个新 pipeline”硬锁。 |
| 独立真实找品 | “开始真实找品” | `POST /api/sourcing/start` | sourcing run | 与 pipeline 的 1688 搜索重复。`Real1688Adapter.active_run()` 能防 active sourcing，但 pipeline 和独立入口并存会让用户困惑。 |
| 旧关键词任务 | “创建找品任务” | `POST /api/candidates/search` | automation run kind `keyword_search` | 与真实 sourcing 和 pipeline 目标重叠；旧路径不等于新真实主流程。 |
| 手工导入链接 | “导入待评估候选” | `POST /api/candidates/import-links` | candidates | 与真实搜索候选池并存；本地 source_url 去重可降低重复，但仍会改变新主流程候选来源。 |
| 手工去重/预检/标题/图片 | 候选区批量按钮 | `/api/candidates/dedupe`、`/api/candidates/precheck`、`/api/products/clean-title`、`/api/images/*` | candidates | 与 pipeline 自动步骤重复；用户可在 pipeline 中途手工改状态，造成统计难解释。 |
| 手工妙手采集 | 候选区/达标池/采集队列 | `POST /api/miaoshou/collect-ready`、`POST /api/collections/bulk-action` | collection run | `validate_candidate()` 会查本地重复，但多个标签页同时点同一候选，在写入 `collection_box_records` 前仍有竞态风险。 |
| 图片生成 | 图片工厂 | `POST /api/images/generate` | generation_jobs/assets | `ACTIVE_GENERATIONS` 防同 job 重复，但多个 job 可针对同一 product 创建，需业务幂等策略。 |
| 铺货批次 | 铺货控制台 | `POST /api/batches/create` | batches/publish_keys | 当前阶段不应进入。`publish_keys` 有预留去重，但旧发布入口仍增加误触风险。 |
| 最终发布确认 | 批次强确认 | `POST /api/batches/:id/confirm` | publish run | `no_publish=true` 会拦截真实发布，但入口可见会干扰新定位。 |
| 失败重试 | 首页/失败中心/运行列表 | `/api/automation/retry-failed`、`/api/failures/action`、`/api/runs/:id/retry` | 多来源失败 | 多套重试入口语义不同，可能重复创建 run 或重复标记 resolution。 |

重点风险：

- 同一商品重复采集：本地 `source_url/source_product_id`、`collection_box_records`、`products` 有保护，但缺少妙手端实时查询和并发锁。
- 同一任务重复启动：前端禁用 active 按钮不足以覆盖多标签页；后端应增加全局运行锁或明确拒绝已有 active pipeline。
- 页面刷新重复提交：事件不会自动重放，但用户可在状态未刷新前再次点击或多标签页操作。
- 失败重试重复创建记录：`automation_retry_failed()` 每次都会创建新 pipeline run，需更清晰的幂等策略。

## 9. 当前是否存在真实一键闭环

结论：当前项目不真正支持“一次点击完成全流程并稳定进入妙手采集箱”。

证据：

1. 代码中有一键主入口和完整编排函数，说明主流程雏形存在。
2. 环境检查、1688 登录、妙手登录、验证码和安全配方都会让流程进入 `waiting_for_manual`。
3. 图片不合格会中断单个候选进入妙手。
4. 妙手采集成功确认主要依赖 CDP runner 返回 ok 并写本地 `collection_box_records`，未确认回读妙手采集箱。
5. pipeline 结束时即使 `collectedToBox == 0` 也可能状态为 `completed`，只是当前步骤显示“处理完成”。
6. 旧五国、图片人工审核、批次发布和多入口仍可见，用户可能偏离新主流程。

当前最早的流程中断点是 Chrome/CDP 或登录/验证码环境检查；在环境全部满足后，最早的结构性中断点通常是妙手采集箱安全配方未配置。

## 10. 本部分明确结论

- 当前项目是否真正支持一次点击完成全流程：不支持。它有一键 pipeline 入口，但真实运行会被 Chrome/CDP、登录验证、验证码、图片不达标、妙手安全配方和采集确认不足打断，不能证明稳定完成“1688 搜索到妙手采集箱”的真实闭环。
- 当前最早在哪一步中断：最早在环境检查阶段中断，即 Chrome/CDP 未就绪、1688 未登录、妙手未登录或检测到验证码/短信/人机验证。
- 当前人工操作最多的阶段：候选处理和旧商品工作台阶段最多，包括选择候选、补供应/市场数据、五国评分、去重、预检、标题、图片、采集、审核和异常处理等大量按钮。
- 当前最容易造成重复处理的阶段：妙手采集和失败重试阶段。候选本地去重已有保护，但多入口 `collect-ready`、采集队列、失败重试和多标签页并发仍可能在写入 `collection_box_records` 前产生竞态。
- 当前哪些旧功能最影响主流程：铺货批次、最终发布确认、发布结果中心、五国评分、图片人工审核和多个手工开始入口。
- 当前哪些底层能力值得保留：本地配置和安全开关、专用 Chrome/CDP、真实 1688 搜索适配、候选去重、风险预检、标题清洗、图片基础判断、妙手安全采集箱适配、日志和失败诊断。
- 当前哪些功能必须先从主流程移出：店铺配置、铺货批次、最终发布确认、发布结果中心、五国复杂评分/设置、演示商品创建、逐步人工操作按钮和独立真实找品/关键词任务/导入链接等重复主入口。
