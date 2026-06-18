# 模块0审计：范围收缩清单

审计时间：2026-06-18

本阶段只做审计与文档整理，不修改业务代码、数据库或页面。

## 1. 保留并复用

| 功能名称 | 当前代码位置 | 当前完成度 | 处理方式 | 后续模块 | 风险说明 |
| --- | --- | --- | --- | --- | --- |
| 本地 Python 服务 | `app.py`、`run.bat`、`启动工作台.command` | B | 保留并直接复用 | 模块1 | 端口和启动方式需统一 |
| SQLite 数据库 | `lib/database.py` | A/B | 保留并直接复用 | 模块1/9 | 需补统一 run_id 和采集幂等 |
| 本地配置和安全开关 | `lib/local_config.py`、`data/config.json` | A | 保留并直接复用 | 模块1 | settings/config 双源需收口 |
| Workbench token 和本机写接口保护 | `app.py`、`lib/local_config.py` | A | 保留并直接复用 | 模块1 | 继续保证只本机和 token |
| 专用 Chrome Profile | `lib/browser_manager.py`、`lib/automation.py` | A | 保留并直接复用 | 模块2 | profile 含登录态，不能泄露 |
| Chrome/CDP 连接 | `lib/browser_manager.py`、`scripts/cdp_probe.mjs` | B | 保留并直接复用 | 模块2 | Chrome 版本和端口不稳定 |
| 1688 登录状态检测 | `lib/browser_manager.py` | B/G | 保留并直接复用 | 模块2/3 | 文本检测需真实验证 |
| 妙手登录状态检测 | `lib/browser_manager.py`、`lib/real_miaoshou_adapter.py` | B/G | 保留并直接复用 | 模块2/8 | 页面变化会误判 |
| 真实 1688 搜索适配 | `lib/real1688_adapter.py`、`scripts/real1688_search.mjs` | B/G | 保留并直接复用 | 模块3 | DOM 选择器易变 |
| 候选商品保存 | `DB.import_candidates()`、`Real1688Adapter.save_results()` | A | 保留并直接复用 | 模块3 | 缺 run_id |
| 去重规则 | `dedupe_candidates()`、`collection_box_records` | A | 保留并直接复用 | 模块4 | 缺妙手端实时去重 |
| 商品筛选规则 | `analyze_candidate_precheck()` | B | 保留并直接复用 | 模块5 | 规则需收口和解释 |
| 标题清洗 | `lib/title_cleaner.py` | A | 保留并直接复用 | 模块6 | 英文标题质量有限 |
| 图片下载 | `lib/image_inspector.py` | B | 保留并直接复用 | 模块7 | URL 失效和下载失败需重试 |
| 图片基础检查 | `lib/image_inspector.py` | C | 保留并直接复用 | 模块7 | 无 OCR/视觉识别 |
| 妙手安全采集适配 | `lib/real_miaoshou_adapter.py` | B/G | 保留并直接复用 | 模块8 | 采集配方和回读确认不足 |
| CDP 执行器 | `scripts/cdp_runner.mjs` | C | 保留并直接复用 | 模块8 | 必须限制危险动作 |
| 自动重试基础 | `resolve_failure_task()`、`automation_retry_failed()` | C | 保留并直接复用 | 模块9 | 重试语义不统一 |
| 运行日志 | `automation_logs`、`pipeline_log()` | A | 保留并直接复用 | 模块9 | 日志可能含敏感 URL/截图 |
| 历史运行记录 | `automation_runs`、`sourcing_runs` | A/B | 保留并直接复用 | 模块9 | 本次运行统计不准 |
| 失败诊断 | `diagnostics()`、`build_diagnostics()` | B | 保留并直接复用 | 模块9 | 截图/可点击文本取决于当前页面 |

保留能力数量：21 项。

## 2. 保留但隐藏

| 功能名称 | 当前代码位置 | 当前完成度 | 处理方式 | 后续模块 | 风险说明 |
| --- | --- | --- | --- | --- | --- |
| Chrome 路径 | `settings.automation.chrome_path`、`resolve_chrome_path()` | C | 首次安装自动检测，失败才高级设置 | 模块1/2 | 普通用户不应配置路径 |
| Chrome 用户目录 | `chrome_profile_dir`、`data/chrome-profile` | A | 使用默认值 | 模块1/2 | 含登录态，隐藏路径细节 |
| CDP 端口 | `chrome_debug_port`、`automation.cdp_port` | A | 使用默认值，高级设置 | 模块2 | 端口冲突时才暴露 |
| 妙手插件 ID/目录 | `automation.plugin_*` | C | 移入高级设置 | 模块8 | 插件配置复杂 |
| 1688 地址 | `automation.alibaba_url` | A | 使用默认值 | 模块2/3 | 除非平台地址变化 |
| 妙手地址 | `automation.miaoshou_url` | A | 使用默认值 | 模块2/8 | 企业环境差异时高级设置 |
| 请求超时时间 | `image.timeout`、CDP subprocess timeout | B | 移入高级设置 | 模块7/8 | 普通用户不应改 |
| 最大重试次数 | `max_retry`、`attempts` | C | 使用默认值，失败中心显示 | 模块9 | 需统一 retry 语义 |
| 并发数量 | `image.concurrency` | B | 使用默认值 | 模块7 | 避免大批量请求 |
| 自动化动作配方 | `automation.*_recipe` | C | 高级设置/开发者可见 | 模块8 | 错误配方会误操作 |
| 页面选择器/点击文本 | `scripts/cdp_runner.mjs`、settings 文本 | C | 仅开发者可见 | 模块8 | 页面变更风险高 |
| 图片接口地址 | `image.base_url`、`image.path` | B | 移入高级设置 | 模块7 | 未配置时不应阻塞原图可用流程 |
| 图片接口请求模板 | `image.request_template` | B | 仅开发者可见 | 模块7 | 模板错误会泄露或失败 |
| 汇率规则 | `market.*.exchange` | A | 暂时保留代码但不提供普通入口 | 后续版本 | 五国定价旧需求 |
| 运费规则 | `market.*.shipping_cny` | A | 暂时保留代码但不提供普通入口 | 后续版本 | 五国定价旧需求 |
| 调试开关/自检修复 | `system_selfcheck()`、`selfcheck_repair()` | B | 高级设置 | 模块9 | 可能创建/修改演示式数据 |
| 详细技术日志 | `automation_logs.details`、diagnostics | A | 普通页摘要，高级详情展开 | 模块9 | 可能含敏感页面文本 |

隐藏能力数量：17 项。

## 3. 改造成自动步骤

| 功能名称 | 当前人工入口 | 当前 API 或函数 | 自动触发条件 | 自动完成条件 | 失败处理 | 是否需人工 | 后续模块 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 创建关键词任务 | `#create-search` | `POST /api/candidates/search`、旧 `keyword_search` | 点击“开始自动选品”后读取 config keywords | 关键词队列生成 | 无关键词则异常 | 首次配置可能需要 | 模块3 |
| 启动 1688 搜索 | `#sourcing-start` | `POST /api/sourcing/start`、`SOURCING.start_run()` | 环境和登录通过 | sourcing run completed | 等待人工/失败重试 | 验证码需要 | 模块3 |
| 商品去重 | `#dedupe-candidates` | `dedupe_candidates()` | 候选保存后 | `dedupe_checked_at` 写入 | 重复跳过，疑似重复跳过 | 异常复核可人工 | 模块4 |
| 商品预检 | `#precheck-candidates` | `precheck_candidates()` | 去重为 new_candidate | `precheck_status` 写入 | 风险阻断/低优先级跳过 | 规则异常可人工 | 模块5 |
| 商品评分 | `#evaluate-selected` | `evaluate_candidates()` | 首版不走五国评分；保留底层参考 | 不进入普通主流程 | 不适用 | 否 | 模块5 |
| 标题清洗 | `#clean-title-candidates` | `clean_titles_for_candidates()` | precheck needs_title_clean 或缺 clean_title | `clean_title` 写入并复查通过 | 失败进入异常列表 | 少数异常 | 模块6 |
| 图片下载 | `#download-images` | `download_candidate_images()` | precheck passed 后 | `local_images`/image record 写入 | 下载失败记录并跳过商品 | 否 | 模块7 |
| 图片处理 | `#analyze-images`、`#auto-process-images` | `auto_process_candidate_images()` | 图片下载后 | `image_status=image_ready` 或 blocked | 不合格进入图片队列/异常 | 仅异常 | 模块7 |
| 妙手采集 | `#collect-qualified`、达标池按钮 | `MIAOSHOU.collect_ready()` | dedupe/precheck/title/image 全通过 | `collection_box_records` 写入且最好回读确认 | 等待人工/失败重试 | 登录/验证码/配方需要 | 模块8 |
| 失败重试 | `#automation-retry-failed`、失败中心按钮 | `automation_retry_failed()`、`resolve_failure_task()` | 商品失败且未超过重试次数 | 原步骤成功或转异常 | 超过次数进入异常列表 | 超过次数需人工 | 模块9 |

需要自动化能力数量：10 项。

## 4. 暂停开发

| 功能名称 | 当前代码位置 | 是否已真实完成 | 为什么暂停 | 是否影响新主流程 | 未来恢复条件 | 当前处理 |
| --- | --- | --- | --- | --- | --- | --- |
| 五国独立评分展示 | `lib/evaluation.py`、候选表、达标池 | 本地逻辑较完整 | 首版只做统一准入和 SEA 粗略适配 | 高，分散注意力 | 主流程稳定后再评估 | 隐藏普通入口 |
| 五国独立商品版本 | `market_versions`、市场弹窗 | 本地逻辑完整 | 当前不做多国家版本 | 高 | 进入铺货版本时恢复 | 隐藏 |
| 人工补充市场数据 | 候选详情弹窗 | 已实现 | 正常流程不应人工逐项补 | 高 | 作为异常修复入口 | 隐藏普通入口 |
| 人工选择候选商品 | 候选 checkbox/达标池 | 已实现 | 一键小批量不应逐个选 | 中 | 高级诊断和异常处理 | 隐藏普通入口 |
| 图片人工审核 | 图片工厂审核按钮 | 已实现 | 首版要求自动判断图片 | 中 | AI 图片质量流程成熟后作为抽检 | 隐藏普通入口 |
| 店铺配置 | `shops`、店铺表单 | 本地完整 | 本阶段不发布到店铺 | 高 | 进入铺货发布版本 | 隔离 |
| 铺货批次 | `batches`、批次预检 | 本地完整 | 本阶段只到采集箱 | 高 | 发布阶段重新启用 | 隔离 |
| 多店铺铺货 | `batches`、`publish_keys` | 本地预检完整，真实未确认 | 当前禁止 | 高 | 合规和发布安全流程完成后 | 暂停 |
| 自动发布 | `AutomationEngine.execute_live(kind='publish')` | 代码存在，安全拦截 | 明确禁止最终发布 | 极高 | 未来另立模块并强门禁 | 暂停且隐藏 |
| 最终发布确认 | 批次强确认弹窗/API | 门禁存在 | 当前不应暴露发布路径 | 极高 | 发布版本恢复 | 隐藏 |
| 复杂工作台导航 | `static/index.html` 全工作台 | 已实现 | 新定位是本地自动化控制台 | 高 | 高级模式再展示 | 收缩入口 |
| 文本本地化/五国语言 | `lib/text_gateway.py` | 部分实现 | 首版采集箱不需要 | 中 | 多国家商品版本恢复 | 暂停 |

暂停能力数量：12 项。

## 5. 本部分明确结论

- 首版最少需要保留：本地服务、SQLite、配置安全开关、专用 Chrome/CDP、登录检测、1688 搜索、候选保存、去重、预检、标题清洗、图片下载/检查、妙手安全采集、日志、失败诊断、历史记录。
- 必须从普通页面隐藏：Chrome/CDP/插件/配方/图片接口/汇率运费/调试日志等高级配置，以及店铺、批次、发布、五国版本和人工审核入口。
- 必须自动化的人工步骤：关键词任务、真实找品、去重、预检、标题清洗、图片下载、图片处理、妙手采集和失败重试。
- 必须暂停的旧功能：五国独立评分展示、五国版本/定价、店铺配置、铺货批次、多店铺铺货、自动发布、最终发布确认、复杂工作台导航。
- 距离真实一键闭环还缺：真实 1688/Miaoshou 实测、插件和链接采集统一、采集箱回读确认、图片质检可靠性、统一 run_id、幂等约束和结果统计隔离。
