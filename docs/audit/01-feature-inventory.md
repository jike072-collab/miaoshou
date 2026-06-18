# 模块0审计：功能真实完成度盘点

审计时间：2026-06-18

状态分类标准：

- A. 已真实完成并可运行
- B. 主要逻辑完成，但依赖外部环境
- C. 仅完成部分逻辑
- D. 只有接口、函数或数据结构
- E. 只有前端界面
- F. 使用模拟数据或演示流程
- G. 尚未实现
- H. 无法确认

说明：本盘点按代码证据判断，不把“有按钮”“有 API”“单元测试通过”直接等同为真实平台闭环完成。

## 1. 本地启动与环境

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1. 本地程序启动 | B | `run.bat`、`启动工作台.command`、`app.py`、`scripts/bootstrap.py` | `main()`、`initialize()`、`GET /api/health` | `data/workbench.db`、`data/config.json` | 否 | `scripts/selfcheck.py`、多数组件测试间接覆盖 | Windows 双击或 mac 双击/命令行 | 是 | Windows 默认 8000，mac/README 默认 8765；mac 脚本不创建 venv |
| 2. 自动打开浏览器 | B | `lib/browser_manager.py`、`lib/automation.py`、`static/app.js` | `BrowserManager.start()`、`POST /api/browser/start`、`AutomationEngine.launch_chrome()` | `data/chrome-profile` | 是，打开真实 Chrome | `tests/test_browser_manager.py`、部分 mock | 首次需要用户点击启动 | 是 | 依赖本机 Chrome 路径；前端当前在 CDP ready 时禁用启动按钮，用户易困惑 |
| 3. 专用Chrome用户目录 | A | `lib/automation.py`、`lib/browser_manager.py`、`lib/local_config.py` | `chrome_profile_dir()`、`profile_dir()`、`DEFAULT_CONFIG.chrome_profile_dir` | `data/chrome-profile/` | 是 | `tests/test_browser_manager.py`、`tests/test_local_config.py` | 首次登录需要人工 | 是 | 目录可能含 Cookie/Login Data，不能提交或读取敏感内容 |
| 4. Chrome或CDP连接 | B | `lib/browser_manager.py`、`lib/automation.py`、`scripts/cdp_probe.mjs` | `cdp_ready()`、`targets()`、`cdp_probe()`、`GET /api/browser/status` | 无，状态实时返回 | 是 | `tests/test_browser_manager.py`、`tests/test_automation.py` | 需要 Chrome 保持开启 | 是 | 依赖 9222 或配置端口；页面文本探测可能失败 |
| 5. 1688登录状态检测 | B | `lib/browser_manager.py`、`lib/automation.py`、`scripts/cdp_probe.mjs` | `detect_alibaba_login()`、`AutomationEngine.alibaba_logged_in()`、`GET /api/platform/status` | 无，状态实时返回 | 是 | `tests/test_browser_manager.py`、`tests/test_automation.py` | 登录和验证需人工 | 是 | 文本标记规则，不能保证所有 1688 页面形态 |
| 6. 妙手登录状态检测 | B | `lib/browser_manager.py`、`lib/automation.py`、`lib/real_miaoshou_adapter.py` | `detect_miaoshou_login()`、`miaoshou_logged_in()`、`GET /api/platform/status`、`GET /api/miaoshou/status` | 无，状态实时返回 | 是 | `tests/test_browser_manager.py`、`tests/test_real_miaoshou_adapter.py` | 登录和验证需人工 | 是 | 文本标记规则，页面改版或不同入口可能误判 |
| 7. 妙手插件检测 | C | `lib/automation.py`、`scripts/cdp_probe.mjs` | `plugin_extension_id()`、`preflight()`、`GET /api/automation/preflight` | `settings.automation.plugin_*` | 是，但只检测目标/文本 | `tests/test_automation.py` | 首次加载插件需人工 | 部分进入 | 只能判断插件目标或页面文本，不证明插件可成功采集 |
| 8. 用户配置保存 | A | `lib/local_config.py`、`lib/database.py`、`app.py` | `load_config()`、`save_config()`、`POST /api/config`、`POST /api/settings` | `data/config.json`、`settings` 表、macOS Keychain | 否 | `tests/test_local_config.py`、`tests/test_database.py` | 需要用户配置 | 是 | 配置分散在 JSON 和 SQLite settings，后续需收口 |
| 9. 搜索关键词配置 | A | `lib/local_config.py`、`lib/real1688_adapter.py`、`data/config*.json` | `DEFAULT_CONFIG.keywords`、`normalize_limits()` | `data/config.json` | 否 | `tests/test_real1688_adapter.py` | 用户可编辑配置 | 是 | 前端没有专门的新手简化配置入口 |
| 56. Windows双击启动 | B | `run.bat` | venv、pip、bootstrap、DB 初始化、启动 8000 | `.venv/`、`data/` | 否 | 无专门 Windows 实机测试 | 双击 | 是 | 当前审计在 macOS，无法实机验收 Windows 双击 |
| 57. macOS双击启动 | B | `启动工作台.command` | 启动 `python3 app.py` 并打开 8765 | `data/` | 否 | `scripts/selfcheck.py` 间接验证服务启动 | 双击 | 是 | 不执行 bootstrap/venv 安装；依赖已有 Python 环境 |
| 58. 配置备份 | G | 未发现明确实现 | 无 | 无 | 否 | 无 | 无 | 否 | 没有自动配置备份策略 |
| 59. 数据库备份 | G | 未发现明确实现 | 无 | 无 | 否 | 无 | 无 | 否 | 没有自动 DB 备份/恢复策略 |

## 2. 1688找品

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10. 1688关键词搜索 | B | `lib/real1688_adapter.py`、`scripts/real1688_search.mjs`、`app.py` | `search_url()`、`run_once()`、`POST /api/sourcing/start` | `sourcing_runs`、`candidates` | 是 | `tests/test_real1688_adapter.py` | 登录/验证码需人工 | 是 | 真实 DOM 未在本审计中实测；依赖 CDP |
| 11. 获取真实搜索结果 | B | `scripts/real1688_search.mjs`、`lib/real1688_adapter.py` | DOM extraction、`extract()`、`save_results()` | `candidates` | 是 | `tests/test_real1688_adapter.py` | 无逐商品人工，验证需人工处理 | 是 | 选择器和文本规则可能随 1688 改版失效 |
| 12. 自动翻页 | C | `lib/real1688_adapter.py`、`scripts/real1688_search.mjs` | `for page in range(...)`、`search_url(... beginPage=)` | `sourcing_runs.current_page` | 是 | `tests/test_real1688_adapter.py` | 否 | 是 | 有页数循环，但未见搜索结束识别；只按配置页数停止 |
| 13. 候选数量停止条件 | A | `lib/real1688_adapter.py`、`lib/local_config.py` | `normalize_limits()`、`remaining = max_items_per_run - saved` | `data/config.json`、`sourcing_runs` | 否 | `tests/test_real1688_adapter.py`、`tests/test_no_publish_guard.py` | 否 | 是 | 上限逻辑按 saved 计数，重复/失败较多时 found 数可能超过直觉 |
| 14. 商品详情页读取 | C | `lib/collector.py`、`app.py` | `scrape_product()`、`refresh_candidate_from_source()`、`POST /api/candidates/:id/refresh-source` | `candidates` | 部分，公网 HTTP 抓取 | `tests/test_collector.py`、`tests/test_workflow.py` | 可手动触发 | 部分进入 | 不复用登录态，1688 动态详情或验证码页可能拿不到真实字段 |
| 27. 发货或销量信息检查 | C | `scripts/real1688_search.mjs`、`lib/evaluation.py`、`app.py` | `parseMonthlySales()`、`sales_text`、`dispatch_hours`、`candidate_data_completeness()` | `candidates` | 部分来自真实搜索页可见文本 | `tests/test_database.py`、`tests/test_automation.py` | 可人工补 | 是 | 搜索页可见字段不稳定；详情页补全有限 |

## 3. 去重与数据管理

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15. 商品链接去重 | A | `app.py`、`lib/database.py` | `normalize_source_url_for_dedupe()`、`dedupe_candidates()`、`POST /api/candidates/dedupe` | `candidates.dedupe_*` | 否，本地数据 | `tests/test_candidate_dedupe.py`、`tests/test_workflow.py` | 否 | 是 | 主要基于本地历史，不查外部平台 |
| 16. 历史采集记录去重 | A | `app.py`、`lib/database.py` | `history_dedupe_indexes()`、`collection_box_records` | `collection_box_records`、`automation_runs` | 否，本地历史 | `tests/test_candidate_dedupe.py`、`tests/test_database.py` | 否 | 是 | 只覆盖本地已记录历史 |
| 17. 妙手已有商品去重 | C | `app.py`、`lib/real_miaoshou_adapter.py` | `collection_box_records` 检查、`products` 检查 | `products`、`collection_box_records` | 否或无法确认 | `tests/test_real_miaoshou_adapter.py` | 否 | 部分进入 | 未发现实时查询妙手已有商品/采集箱列表的实现 |
| 60. 店铺配置 | A | `lib/database.py`、`app.py`、`static/index.html` | `shops` 表、`POST /api/shops` | `shops` | 否 | `tests/test_batch.py`、`tests/test_workflow.py` | 需要人工配置 | 旧流程 | 属于铺货发布旧需求，新主流程可隐藏 |

## 4. 风险和商品筛选

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 18. 风险词检查 | A | `app.py`、`lib/title_cleaner.py` | `candidate_risk_hits()`、`analyze_candidate_precheck()` | `candidates.precheck_*` | 否，规则判断 | `tests/test_workflow.py` | 否 | 是 | 词表规则，覆盖范围需持续维护 |
| 19. 品牌词检查 | C | `app.py`、`lib/title_cleaner.py` | `RISK_KEYWORD_GROUPS`、`RISK_MARKETING_TERMS` | `candidates.precheck_*`、`title_cleaning_records` | 否 | `tests/test_title_cleaner.py`、`tests/test_workflow.py` | 否 | 是 | 没有品牌库或商标库，只能命中词表 |
| 20. 侵权风险检查 | C | `app.py` | `candidate_risk_hits()` | `candidates.precheck_*` | 否 | `tests/test_workflow.py` | 否 | 是 | 规则拦截“高仿/复刻/原单”等，不能真实识别全部侵权 |
| 21. 平台禁限售检查 | C | `app.py`、`lib/evaluation.py` | `RISK_KEYWORD_GROUPS`、`hard_blocks` | `candidates.precheck_*`、`evaluations` | 否 | `tests/test_evaluation.py`、`tests/test_workflow.py` | 否 | 是 | 无 TikTok Shop 官方类目/禁售实时规则同步 |
| 22. 季节判断 | A | `app.py` | `current_season_fit_status()` | `candidates.season_fit_status` | 否 | `tests/test_workflow.py` | 否 | 是 | 基于当前月份和关键词，较粗糙 |
| 23. 价格筛选 | C | `app.py`、`lib/evaluation.py` | `sea_fit_status()`、`evaluate_candidate()`、`batch_margin_pct()` | `candidates`、`evaluations`、`market_versions` | 否 | `tests/test_evaluation.py`、`tests/test_batch.py` | 可人工补 | 是 | 新主流程只有粗略价格带；旧五国利润计算较复杂 |
| 24. 重量筛选 | C | `app.py`、`lib/evaluation.py` | `sea_fit_status()`、`evaluate_candidate()` | `candidates.weight_g`、`evaluations` | 否 | `tests/test_evaluation.py` | 可人工补 | 是 | 依赖候选重量字段是否能获取/补齐 |
| 25. SKU完整性检查 | A | `app.py`、`lib/evaluation.py` | `analyze_candidate_precheck()`、`evaluate_candidate()` | `candidates.sku_complete` | 否 | `tests/test_evaluation.py`、`tests/test_workflow.py` | 可人工补 | 是 | 目前是布尔字段，不解析真实 SKU 列表 |
| 26. 供应商信息检查 | C | `scripts/real1688_search.mjs`、`app.py` | `supplier_name`、`shop_url`、`candidate_data_completeness()` | `candidates` | 部分来自真实搜索页 | `tests/test_database.py` | 可人工补 | 部分进入 | 未见供应商资质/稳定性实时校验 |
| 28. 利润计算 | C | `lib/evaluation.py`、`app.py` | `evaluate_candidate()`、`batch_margin_pct()` | `evaluations.metrics`、`market_versions` | 否 | `tests/test_evaluation.py`、`tests/test_batch.py` | 需目标价/店铺配置 | 旧流程为主 | 新目标不做五国定价，利润计算需降级为筛选参考 |
| 29. 五国评分 | A | `lib/evaluation.py`、`app.py`、`static/app.js` | `evaluate_candidate()`、`evaluation_status()`、`POST /api/candidates/evaluate` | `evaluations` | 否 | `tests/test_evaluation.py`、`tests/test_workflow.py` | 需补市场数据 | 旧流程 | 功能完成度较高，但不属于新简化主流程 |
| 30. 统一商品准入判断 | C | `app.py`、`lib/real_miaoshou_adapter.py` | `analyze_candidate_precheck()`、`candidate_summary()`、`validate_candidate()` | `candidates` | 否 | `tests/test_workflow.py`、`tests/test_real_miaoshou_adapter.py` | 否 | 是 | 准入分散在 precheck、summary、Miaoshou validate，多处规则需收口 |

## 5. 标题处理

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 31. 标题清洗 | A | `lib/title_cleaner.py`、`app.py` | `TitleCleaner.clean()`、`clean_candidate_title()`、`POST /api/products/clean-title` | `candidates.clean_title`、`title_cleaning_records` | 否 | `tests/test_title_cleaner.py`、`tests/test_workflow.py` | 否 | 是 | 规则映射，语义质量有限 |
| 32. 品牌词删除 | C | `lib/title_cleaner.py`、`app.py` | `SUPPLY_CHAIN_TERMS`、`RISK_MARKETING_TERMS`、`candidate_risk_hits()` | `title_cleaning_records` | 否 | `tests/test_title_cleaner.py` | 否 | 是 | 没有独立品牌词库；只覆盖风险词和平台词 |
| 33. 违规词删除 | A | `lib/title_cleaner.py` | `RISK_MARKETING_TERMS`、`analyze_terms()` | `title_cleaning_records` | 否 | `tests/test_title_cleaner.py` | 否 | 是 | 词表需持续维护 |
| 34. 英文标题生成 | C | `lib/title_cleaner.py`、`lib/text_gateway.py` | `_english_title()`、`_fallback_title()`、`localize()` | `candidates.clean_title`、`market_versions` | 否，除 text relay 外 | `tests/test_title_cleaner.py`、`tests/test_text_gateway.py` | 否 | 是 | 标题清洗用规则映射，不是真实翻译；text relay 属旧本地化流程 |

## 6. 图片处理

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 35. 商品图片下载 | B | `lib/image_inspector.py`、`lib/collector.py`、`app.py` | `fetch_image()`、`analyze_candidate_images()`、`POST /api/images/download` | `data/images/{candidate_id}`、`candidates.local_images`、`image_analysis_records` | 是，下载真实 URL | `tests/test_image_inspector.py`、`tests/test_workflow.py` | 否 | 是 | 依赖图片 URL 可访问；失败只记录，不阻塞整批 |
| 36. 图片质量检查 | C | `lib/image_inspector.py` | `inspect_image_source()`、`_image_size_bytes()` | `candidates.image_*`、`image_analysis_records` | 否，规则判断 | `tests/test_image_inspector.py` | 否 | 是 | 无真实 OCR/视觉识别，不能可靠判断图内中文、水印、二维码 |
| 37. 图片自动处理 | C | `app.py`、`lib/image_inspector.py`、`lib/image_gateway.py` | `auto_process_candidate_images()`、`generate()` | `candidates.image_status`、`generation_jobs`、`assets` | 部分依赖外部中转站 | `tests/test_image_gateway.py`、`tests/test_workflow.py` | 不合格时可能需后续处理 | 是 | 候选图片不合格时目前多为 `needs_generation`，不会自动清洗原图 |
| 38. 图片生成接口 | B | `lib/image_gateway.py`、`app.py`、`lib/prompts.py` | `generate()`、`create_generation_job()`、`POST /api/images/generate` | `generation_jobs`、`assets`、`data/assets` | 是，依赖外部图片中转站 | `tests/test_image_gateway.py`、`scripts/selfcheck.py` 使用 mock relay | 需要配置中转站/API Key | 部分进入 | 未配置时不可用；主流程阶段应先允许“原图可用即通过” |
| 39. 图片自动质检 | C | `lib/image_inspector.py` | `analyze_candidate_images()` | `image_analysis_records` | 否，基础规则 | `tests/test_image_inspector.py` | 否 | 是 | 自动质检不是视觉 AI，只能做下载/尺寸/URL 文本规则 |
| 40. 图片人工审核 | A | `app.py`、`static/index.html`、`static/app.js` | `approve_asset()`、`reject_asset()`、`POST /api/images/:id/approve|reject` | `assets.review_status`、`assets.approved` | 否 | `tests/test_workflow.py` | 需要人工 | 旧流程 | 新目标“不正常流程逐商品人工审核”，应隐藏或仅异常处理 |

## 7. 妙手采集

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 41. 妙手插件采集 | C | `lib/automation.py`、`scripts/cdp_runner.mjs` | `execute_live(kind='collection')`、`clickText()` | `automation_runs`、`candidates.collected_at` | 是，依赖插件页面 | `tests/test_automation.py` | 插件安装/登录需人工 | 部分进入 | 新安全适配层更多使用采集箱配方；插件成功闭环未实机确认 |
| 42. 妙手链接采集 | B | `lib/real_miaoshou_adapter.py`、`lib/automation.py`、`scripts/cdp_runner.mjs` | `safe_recipe()`、`invoke_safe_recipe()`、`link_collection_recipe` | `automation_runs`、`collection_box_records` | 是，依赖妙手页面和配方 | `tests/test_real_miaoshou_adapter.py` | 配方校准需人工 | 是 | 没有默认真实配方；未校准时会等待人工 |
| 43. 插件失败后兜底 | C | `lib/automation.py` | fallback to `automation.link_collection_recipe` | `automation_runs` | 是，依赖配方 | `tests/test_automation.py` | 配方需人工 | 部分进入 | 兜底在旧 AutomationEngine 中，新 RealMiaoshouAdapter 以安全配方为主，需统一 |
| 44. 采集成功确认 | C | `lib/real_miaoshou_adapter.py`、`lib/automation.py` | `collect_candidate()` 写 `collection_box_records`、`plugin_success_texts` | `collection_box_records`、`automation_runs` | 部分真实 | `tests/test_real_miaoshou_adapter.py`、`tests/test_database.py` | 否 | 是 | 当前成功确认主要依赖 runner 返回 ok 或插件成功文本，不一定回读妙手采集箱列表 |
| 45. 妙手商品编号记录 | G | 未发现明确字段 | 无 | 无专门字段 | 否 | 无 | 无 | 否 | `collection_box_records` 记录 candidate/offer/source_url/run_id，但未见妙手商品编号 |

## 8. 任务控制

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 46. 自动重试 | C | `app.py`、`lib/automation.py` | `/api/runs/:id/retry`、`retry_generation_job()`、`automation_retry_failed()` | `automation_runs.attempts`、`generation_jobs.attempts` | 否，重试调度 | `tests/test_workflow.py`、`scripts/selfcheck.py` | 需用户点击重试 | 是 | 真实平台失败重试是否幂等依赖配方和页面状态 |
| 47. 任务暂停 | B | `app.py`、`lib/real1688_adapter.py` | `automation_pause()`、`SOURCING.pause()`、`POST /api/automation/pause` | `automation_runs.context`、`sourcing_runs.status` | 否，控制本地流程 | `tests/test_workflow.py` | 用户点击或验证触发 | 是 | 正在执行的 CDP 子进程不能立即中断，只能在轮询点生效 |
| 48. 任务继续 | B | `app.py`、`lib/real1688_adapter.py` | `automation_resume()`、`SOURCING.resume()` | `automation_runs`、`sourcing_runs` | 否，控制本地流程 | `tests/test_workflow.py` | 用户点击 | 是 | 继续后是否断点准确取决于 run context 和候选状态 |
| 49. 任务停止 | B | `app.py`、`lib/real1688_adapter.py` | `automation_stop()`、`SOURCING.stop()` | `automation_runs`、`sourcing_runs` | 否，控制本地流程 | `tests/test_workflow.py` | 用户点击 | 是 | 与暂停类似，正在执行的外部动作不会被强杀 |
| 50. 程序重启后任务恢复 | C | `app.py`、`scripts/selfcheck.py` | `initialize()`、`recover_background_jobs()` | `automation_runs`、`generation_jobs`、`sourcing_runs` | 否，本地恢复 | `scripts/selfcheck.py` | 可能需要人工继续 | 部分进入 | queued 会恢复；running/preparing 被重置 queued；sourcing active 变 waiting_for_manual，不是真正断点续跑 |
| 51. 断点续跑 | C | `app.py` | `pipeline_context()`、`candidates_for_pipeline()`、`pipeline_process_candidates()` | `automation_runs.context`、候选状态 | 否，本地状态 | `tests/test_workflow.py` | 可能需用户继续 | 是 | 有按候选状态跳过已处理的能力，但没有精确恢复到页面动作级断点 |

## 9. 重试与恢复

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 任务失败详情诊断 | B | `lib/real_miaoshou_adapter.py`、`lib/automation.py`、`app.py` | `diagnostics()`、`build_diagnostics()`、`automation_failures()` | `automation_runs.diagnostics`、`automation_logs` | 部分真实，含 URL/截图 | `tests/test_real_miaoshou_adapter.py`、`tests/test_workflow.py` | 查看/处理需人工 | 是 | 截图和可点击文本取决于 CDP 当前页面 |
| 失败任务操作 | B | `app.py`、`static/app.js` | `resolve_failure_task()`、`POST /api/failures/action` | 多表 resolution/status | 否，本地状态 | `tests/test_workflow.py` | 用户点击 | 是 | 不同来源的失败状态处理语义不完全一致 |

## 10. 结果与日志

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 52. 运行日志 | A | `lib/database.py`、`app.py`、`static/app.js` | `save_automation_log()`、`pipeline_log()`、`GET /api/automation/logs` | `automation_logs` | 否，本地记录 | `tests/test_database.py`、`tests/test_workflow.py` | 查看需用户 | 是 | 真实平台截图/URL只有失败或外部动作提供时完整 |
| 53. 结果统计 | A | `app.py`、`static/app.js` | `pipeline_counters()`、`automation_current_status()`、`workflow_summary()` | 多表聚合 | 否，本地统计 | `tests/test_workflow.py` | 否 | 是 | 统计混合旧发布流和新采集流，需收口显示 |
| 54. 异常商品列表 | A | `app.py`、`static/app.js` | `automation_failures()`、`publish_results_summary()`、`GET /api/automation/failures` | `automation_logs`、`automation_runs`、`generation_jobs`、`assets`、`publish_keys` | 否，本地汇总 | `tests/test_workflow.py` | 用户处理 | 是 | 仍包含旧发布失败类型，新主流程应过滤/分组 |
| 55. 历史运行记录 | A | `lib/database.py`、`app.py` | `automation_runs`、`sourcing_runs`、`GET /api/runs`、`GET /api/sourcing/current` | SQLite | 否 | `tests/test_database.py`、`tests/test_real1688_adapter.py` | 查看需用户 | 是 | 历史只保留最近 runs 查询限制；缺少归档和备份 |

## 11. 店铺铺货与发布

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 61. 铺货批次 | A | `app.py`、`lib/database.py`、`static/index.html` | `batch_preflight()`、`create_batch_from_payload()`、`POST /api/batches/create` | `batches`、`publish_keys` | 否，主要本地预检/演练 | `tests/test_batch.py`、`tests/test_workflow.py` | 需要用户选择商品店铺 | 旧流程 | 新阶段明确不做多店铺铺货，建议隐藏 |
| 62. 自动发布 | C | `lib/automation.py`、`app.py`、`scripts/cdp_runner.mjs` | `execute_live(kind='publish')`、`confirm_publish()`、`publish_recipe` | `automation_runs`、`publish_keys` | 代码可调用真实页面配方，但默认安全拦截 | `tests/test_no_publish_guard.py`、`tests/test_batch.py` | 强确认/配方需人工 | 禁止进入 | 当前阶段禁止自动发布；保留代码存在误触风险，需继续被安全层拦截并隐藏入口 |
| 63. 最终发布确认 | A/C | `app.py`、`static/index.html`、`static/app.js` | `batch_confirmation_phrase()`、`require_batch_confirmation()`、`confirm_batch()` | `batches`、`automation_runs` | 否或被 no_publish 拦截 | `tests/test_batch.py`、`tests/test_no_publish_guard.py` | 需要输入确认短语 | 禁止进入 | 确认门禁存在，但新阶段不应暴露最终发布路径 |

## 12. 跨平台支持

| 功能 | 状态 | 文件位置 | 关键函数/API | 数据保存位置 | 是否真实平台 | 是否有测试 | 是否人工操作 | 是否进入新流程 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Chrome 路径跨平台 | C | `lib/automation.py`、`run.bat`、`启动工作台.command` | `resolve_chrome_path()` | SQLite settings、config | 是 | `tests/test_automation.py` 当前 1 例失败 | 用户可配置路径 | 是 | 代码偏 macOS 默认路径；Windows Chrome 自动发现不充分 |
| 密钥跨平台 | C | `lib/keychain.py` | `get_secret()`、`set_secret()` | macOS Keychain | 否 | 无 Windows 测试 | 需用户配置 | 部分进入 | 只支持 macOS Keychain，Windows 无替代实现 |

## 真实性重点结论

### 1688

代码确实存在真实打开 1688 搜索页并提取搜索结果的路径：`Real1688Adapter.extract()` 调用 `scripts/real1688_search.mjs`，后者通过 CDP 导航到 `s.1688.com/selloffer/offer_search.htm`，从 DOM 链接中提取 offer_id、标题、主图、价格、起批量、销量文本、供应商、店铺链接、发货地、类目、关键词、页码和排名。

但当前真实性等级不应判为 A：翻页结束识别未完善，DOM 选择器易受页面改版影响，登录/验证码依赖文本检测，详情页补全使用公网 HTML 抓取而非登录态浏览器，真实搜索闭环需要实机验证。

### 妙手

代码存在真实妙手适配：`RealMiaoshouAdapter.collect_candidate()` 会启动妙手页面、检测登录和验证码、扫描危险发布文本、校验 `no_publish=true`、执行安全采集箱配方，并写入 `collection_box_records`。失败时会保存步骤、错误、当前 URL、截图、可点击文本摘要和建议动作。

但当前真实性等级不应判为 A：默认没有真实妙手采集箱配方，不能确认已真实提交 1688 商品链接并回读采集箱；妙手已有商品去重也未见实时查询妙手端记录；插件采集和链接采集兜底仍依赖页面结构与用户校准。

### 图片

图片来源可以是真实 1688 搜索结果或候选图片 URL，`fetch_image()` 会真实下载，`analyze_candidate_images()` 会保存本地文件并记录失败。原图合格时可直接标记 `image_ready`，不合格会阻止进入妙手采集箱。

但图片判断目前主要是尺寸解析和 URL/文件名关键词规则，没有 OCR 或视觉模型，不能可靠识别图片内部中文、水印、联系方式或二维码。图片自动处理接口存在，但依赖外部图片中转站，不是默认稳定能力。

## 测试现状

- `python3 -m py_compile app.py lib/*.py`：通过。
- `python3 -m unittest discover -s tests -v`：150 个测试，149 通过，1 失败。
- 失败项：`test_resolve_chrome_path_can_find_running_translocated_app`，实际返回固定安装 Chrome 路径，测试期望 mocked 的 AppTranslocation 路径。
- 现有测试大量覆盖本地确定性逻辑、mock CDP/平台状态、mock 图片中转站和本地 API；它们不能证明真实 1688 或真实妙手端到端采集已稳定可用。
