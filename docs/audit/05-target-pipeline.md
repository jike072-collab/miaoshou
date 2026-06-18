# 模块0审计：目标主流程完成度

审计时间：2026-06-18

本阶段只做审计与文档整理，不修改业务代码、数据库或页面。

状态分类：

- A. 已存在，可直接接入
- B. 已存在，但需要改造
- C. 部分存在
- D. 只有接口或数据结构
- E. 使用模拟逻辑
- F. 完全缺失
- G. 依赖外部环境，尚未验证

## 1. 唯一目标流程

后续项目只围绕“本地配置 -> 环境检查 -> 1688 自动找品 -> 自动去重筛选 -> 标题图片处理 -> 妙手采集箱 -> 结果统计”推进。流程不包含店铺铺货、TikTok 最终发布、五国商品版本、五国定价，也不把人工逐商品审核作为正常路径。

## 2. 37 步完成度

| # | 目标步骤 | 状态 | 当前代码位置 | 当前调用入口 | 是否进入真实流程 | 缺少什么 | 后续模块 | 首版必须 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 加载用户配置 | A | `lib/local_config.py`、`app.py` | `load_config()`、`GET/POST /api/config` | 是 | 配置展示需收口，减少 settings/config 双源困惑 | 模块1 | 是 |
| 2 | 检查本地运行环境 | B | `scripts/bootstrap.py`、`app.py`、`run.bat`、`system_selfcheck()` | 启动脚本、`GET /api/local/status`、`GET /api/selfcheck` | 部分 | Windows/mac 启动口径和自检结果需合并 | 模块1 | 是 |
| 3 | 检查Chrome连接 | A | `lib/browser_manager.py` | `GET /api/browser/status`、pipeline env | 是 | 前端按钮和状态提示需简化 | 模块2 | 是 |
| 4 | 检查1688登录状态 | G | `lib/browser_manager.py`、`scripts/cdp_probe.mjs` | `GET /api/platform/status`、pipeline env | 是，依赖真实页面 | 真实页面文本稳定性验证 | 模块2/3 | 是 |
| 5 | 检查妙手登录状态 | G | `lib/browser_manager.py`、`lib/real_miaoshou_adapter.py` | `GET /api/platform/status`、`GET /api/miaoshou/status` | 是，依赖真实页面 | 真实妙手页面状态验证 | 模块2/8 | 是 |
| 6 | 检查妙手插件 | C | `lib/automation.py`、`scripts/cdp_probe.mjs` | `GET /api/automation/preflight` | 部分 | 只能检测目标/文本，不证明插件可采集 | 模块8 | 是 |
| 7 | 根据配置生成搜索关键词 | B | `lib/local_config.py`、`lib/real1688_adapter.py` | `normalize_limits()` | 是 | 目前直接读取配置，缺少关键词扩展/去重策略 | 模块3 | 是 |
| 8 | 打开1688并执行搜索 | G | `lib/real1688_adapter.py`、`scripts/real1688_search.mjs` | `POST /api/sourcing/start`、pipeline | 是，尚需实测 | DOM 选择器和登录态验证 | 模块3 | 是 |
| 9 | 自动翻页获取候选商品 | C | `Real1688Adapter.run_once()`、`search_url()` | pipeline/sourcing | 是 | 只按配置页数循环，缺少搜索结束识别 | 模块3 | 是 |
| 10 | 达到候选数量后停止 | A | `normalize_limits()`、`remaining` | pipeline/sourcing | 是 | 按 saved 数停止，需优化 found/skipped 口径 | 模块3 | 是 |
| 11 | 保存候选商品 | A | `Real1688Adapter.save_results()`、`DB.import_candidates()` | pipeline/sourcing | 是 | 候选缺少 pipeline_run_id | 模块3/后续DB | 是 |
| 12 | 检查历史记录并去重 | A | `dedupe_candidates()`、`collection_box_records` | pipeline、`POST /api/candidates/dedupe` | 是 | 缺少妙手端实时历史查询和 DB 唯一约束 | 模块4 | 是 |
| 13 | 检查高风险词 | A | `candidate_risk_hits()`、`RISK_KEYWORD_GROUPS` | `precheck_candidates()` | 是 | 词表维护和命中解释需产品化 | 模块5 | 是 |
| 14 | 检查品牌和侵权风险 | C | `RISK_KEYWORD_GROUPS`、`TitleCleaner` | `precheck_candidates()` | 是，本地规则 | 缺少品牌库/商标库 | 模块5 | 是 |
| 15 | 检查禁限售风险 | C | `RISK_KEYWORD_GROUPS`、`lib/evaluation.py` | `precheck_candidates()` | 是，本地规则 | 缺少 TikTok 官方类目/禁售规则同步 | 模块5 | 是 |
| 16 | 检查当前季节 | A | `current_season_fit_status()` | `precheck_candidates()` | 是 | 规则粗糙，需可解释配置 | 模块5 | 是 |
| 17 | 检查价格范围 | C | `sea_fit_status()`、`evaluate_candidate()` | `precheck_candidates()`/旧评分 | 部分 | 新主流程价格带需统一，不依赖五国目标价 | 模块5 | 是 |
| 18 | 检查重量 | C | `sea_fit_status()`、`evaluate_candidate()` | `precheck_candidates()`/旧评分 | 部分 | 真实重量来源不稳定 | 模块5 | 是 |
| 19 | 检查SKU完整性 | C | `analyze_candidate_precheck()` | `precheck_candidates()` | 是 | 目前是布尔字段，不解析真实 SKU | 模块5 | 是 |
| 20 | 检查供应商基础信息 | C | `scripts/real1688_search.mjs`、`candidate_data_completeness()` | 1688 搜索/候选补全 | 部分 | 未校验供应商资质和稳定性 | 模块5 | 是 |
| 21 | 计算基础利润 | B | `lib/evaluation.py`、`batch_margin_pct()` | 旧五国评分/批次预检 | 否，旧流程为主 | 改成单一基础利润估算，不依赖五国定价 | 模块5 | 是 |
| 22 | 执行统一准入判断 | B | `analyze_candidate_precheck()`、`RealMiaoshouAdapter.validate_candidate()` | pipeline | 是 | 准入规则分散，需收口成单一状态机 | 模块5/8 | 是 |
| 23 | 自动清洗标题 | A | `lib/title_cleaner.py`、`clean_titles_for_candidates()` | pipeline、`POST /api/products/clean-title` | 是 | 英文质量有限 | 模块6 | 是 |
| 24 | 必要时生成英文标题 | C | `TitleCleaner._english_title()`、`lib/text_gateway.py` | 标题清洗/旧本地化 | 部分 | 规则翻译有限，text gateway 属旧五国本地化 | 模块6 | 是 |
| 25 | 下载商品图片 | B | `lib/image_inspector.py`、`fetch_image()` | pipeline、`POST /api/images/download` | 是，依赖 URL | 图片下载失败重试和 run_id 关联不足 | 模块7 | 是 |
| 26 | 检查图片质量 | C | `inspect_image_source()`、`analyze_candidate_images()` | pipeline、`POST /api/images/analyze` | 是，本地规则 | 无 OCR/视觉模型，不能可靠识别图中文字/水印 | 模块7 | 是 |
| 27 | 仅在需要时处理图片 | C | `auto_process_candidate_images()`、`lib/image_gateway.py` | pipeline、图片接口 | 部分 | 不合格图片多标记 needs_generation，未稳定自动清洗 | 模块7 | 是 |
| 28 | 自动检查处理结果 | C | `image_analysis_records`、`assets.review_status` | 图片工厂/候选图片分析 | 部分 | 生成图和候选图质检未统一；人工审核仍显性 | 模块7 | 是 |
| 29 | 创建妙手采集任务 | A | `RealMiaoshouAdapter.create_run()`、`collect_ready()` | pipeline、`POST /api/miaoshou/collect-ready` | 是 | 需 candidate 级并发锁和 run_id 贯穿 | 模块8 | 是 |
| 30 | 优先调用妙手插件采集 | C | `lib/automation.py`、`scripts/cdp_runner.mjs` | 旧 collection run | 部分 | 新 RealMiaoshouAdapter 当前更偏安全配方；插件优先策略未统一 | 模块8 | 是 |
| 31 | 插件失败后使用链接采集兜底 | C | `AutomationEngine.execute_live()` fallback、`RealMiaoshouAdapter.safe_recipe()` | 旧 collection/新适配 | 部分 | 插件和链接兜底路径需合并成一个安全状态机 | 模块8 | 是 |
| 32 | 检查商品是否进入妙手采集箱 | C | `RealMiaoshouAdapter.collect_candidate()` | 采集后写本地记录 | 部分 | 缺少回读妙手采集箱确认 | 模块8 | 是 |
| 33 | 保存采集成功记录 | B | `collection_box_records`、`save_collection_box_record()` | RealMiaoshouAdapter | 是 | 缺唯一约束和妙手商品编号 | 模块8/DB | 是 |
| 34 | 失败时自动重试 | C | `automation_retry_failed()`、`resolve_failure_task()`、`retry_generation_job()` | 失败中心 | 部分 | pipeline retry 与 run retry 不统一；真实妙手重试幂等不足 | 模块9 | 是 |
| 35 | 超过重试次数后进入异常列表 | B | `automation_failures()`、`publish_results_summary()` | `GET /api/automation/failures` | 是，本地 | 失败来源混旧发布流，重试次数不统一 | 模块9 | 是 |
| 36 | 汇总本次运行结果 | B | `automation_current_status()`、`pipeline_counters()` | 首页自动化控制台 | 是 | 当前按全库统计，无法准确限定本次 run | 模块9/DB | 是 |
| 37 | 保存历史记录 | B | `automation_runs`、`sourcing_runs`、`automation_logs` | 所有流程 | 是 | 缺少归档、备份和统一 run_id | 模块9/后续 | 是 |

## 3. 目标流程统计

- 目标流程共 37 步。
- A 已存在、可直接接入：9 步。
- B 已存在、需要改造：10 步。
- C 部分存在：15 步。
- D 只有接口或数据结构：0 步。
- E 使用模拟逻辑：0 步。
- F 完全缺失：0 步。
- G 依赖外部环境、尚未验证：3 步。

说明：没有标 F 不代表已经闭环完成，而是当前代码对 37 步均已有某种基础能力；真正阻塞在真实性验证、状态一致性、妙手回读、图片质检、run_id 和幂等。

## 4. 本部分结论

首版仍需要把 1688 搜索、妙手采集、图片判断、失败重试和本次运行统计从“存在能力”改成“稳定串联”。最大缺口不是缺少函数，而是缺少真实平台验证、统一运行 ID、采集成功回读确认、图片质检可靠性和普通页面入口收缩。
