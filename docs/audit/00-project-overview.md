# 模块0审计：项目结构与现状概览

审计时间：2026-06-18

审计分支：`feature/00-project-audit`

审计范围：仓库源码、前端、后端、数据库初始化、自动化脚本、启动脚本、配置、安全层、测试与现有文档。

本阶段只做审计与文档整理，不修改业务代码。

## 当前项目定位对照

当前代码仍是一个较完整的“本地网页工作台”：包含候选导入、五国评分、AI 图片、批次预检、演练发布、失败中心、设置页和真实 Chrome/CDP 适配。新的目标则是收缩为“一键本地自动化选品与妙手采集工具”，主流程应围绕：

加载配置 -> 检查环境 -> 1688 自动找品 -> 自动去重 -> 自动筛选 -> 标题和图片处理 -> 妙手采集箱 -> 结果统计。

现阶段安全边界要求只进入妙手采集箱/草稿/待处理区，不执行最终发布。代码中已经存在 `no_publish`、`dry_run_collect`、`collect_to_box_only`、本地 token、CDP 检测和危险发布文本拦截，但旧版铺货批次与发布工作台仍然暴露在界面和接口中，需要后续模块按“保留、隐藏、改造、暂停”分类处理。

## 仓库结构审计

| 文件或目录 | 主要用途 | 关联业务功能 | 是否属于新自动化主流程 | 可复用性 | 后续改造 | 旧需求/可隐藏 | 明显风险 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `README.md` | 项目说明、启动、配置、评估规则、图片中转站、安全边界 | 旧五国工作台、妙手插件、图片生图、批次发布 | 部分属于 | 可复用安全说明与启动说明 | 需改成新定位的一键采集工具说明 | 五国店群、批次发布说明偏旧 | README 默认端口 `8765`，Windows 脚本为 `8000`，定位不一致 |
| `app.py` | HTTP 服务、API 路由、业务编排、候选/预检/去重/图片/批次/自动化主流程 | 几乎全部业务 | 是，但混有旧发布流 | 主流程函数、API、状态计算可复用 | 需拆分并隐藏旧复杂工作台入口 | 批次、五国版本、真实发布相关应暂停/隐藏 | 单文件 4800+ 行，职责过重；真实闭环依赖外部页面和配置 |
| `lib/database.py` | SQLite schema、迁移兼容、CRUD、settings seed | candidates、sourcing_runs、collection_box_records、title/image records、products、batches、automation_runs/logs、publish_keys | 是 | 数据模型较完整，可保留 | 需围绕新主流程简化可见状态 | market_versions、batches、publish_keys 属旧铺货发布需求 | 本地 DB 存所有运行状态；需谨慎备份和隐私边界 |
| `lib/local_config.py` | `data/config.json`、runtime 目录、token、安全开关、发布动作拦截 | 本地启动、安全边界、真实小批量限制 | 是 | 高 | 需作为后续所有真实动作的统一安全入口 | 无 | `local_status()` 会把 token 返回给前端；适合本机页面，但要保持只允许本机访问 |
| `lib/browser_manager.py` | 专用 Chrome/CDP 管理、状态检测、截图、1688/妙手登录与验证码文本检测 | 环境检查、人工验证暂停 | 是 | 高 | 需补跨平台 Chrome 路径策略和按钮交互问题 | 无 | 登录/验证码判断依赖页面文本，可能随平台变化误判 |
| `lib/real1688_adapter.py` | 真实 1688 搜索运行器包装、关键词/分页/数量限制、保存候选、触发去重预检 | 1688 自动找品 | 是 | 中高 | 需实机验证真实页面 DOM 稳定性和翻页结束识别 | 无 | 依赖 `scripts/real1688_search.mjs` DOM 选择器；搜索失败或页面改版会中断 |
| `lib/real_miaoshou_adapter.py` | 真实妙手采集箱安全适配、候选准入校验、危险按钮扫描、配方执行、失败诊断 | 妙手采集箱/待处理区 | 是 | 中高 | 需校准真实妙手采集箱安全配方并实测 | 发布相关动作严格不应进入 | 真实采集依赖用户配置配方；页面出现“发布/上架/提交”会暂停 |
| `lib/automation.py` | 旧自动化状态机、Chrome 预检、CDP runner 调用、插件采集、发布演练/确认、诊断 | 插件采集、链接采集、发布流程、preflight | 部分属于 | CDP runner、诊断和安全门禁可复用 | 新主流程应只保留采集箱相关能力 | 发布准备/最终确认属于暂停或隐藏 | 与 `RealMiaoshouAdapter` 职责重叠；发布逻辑仍存在 |
| `lib/collector.py` | 公共 URL 安全校验、商品详情 HTML 元信息抓取、图片下载 | 链接补数据、图片下载 | 部分属于 | 可复用 | 需确认 1688 详情页是否能通过公开 HTML 获取足够字段 | 手工链接补数据不是新主入口 | 详情抓取不走登录态，动态页面字段可能拿不到 |
| `lib/evaluation.py` | 确定性五国评分、hard block、置信度 | 五国评分、旧达标池 | 旧需求为主 | 可作为风险/数据完整性规则参考 | 新流程不应暴露五国复杂评分 | 五国独立定价/版本应隐藏 | 市场数据多为用户输入或默认值，不代表真实 TikTok 市场判断 |
| `lib/title_cleaner.py` | 供应链词、平台词、风险营销词移除，简单英文标题生成 | 标题清洗 | 是 | 高 | 可继续扩展词表和语言质量 | 无 | 英文标题是规则映射，不是真正语义翻译 |
| `lib/image_inspector.py` | 图片 URL 下载、尺寸解析、URL/文件名规则检测、水印/平台/联系方式/二维码关键词判断 | 图片自动判断 | 是 | 中 | 需接入真实 OCR/视觉检测或明确为基础规则 | 人工审核流可隐藏 | 无 OCR，不能真实识别图片内中文/水印，只能根据 URL/文件名和尺寸判断 |
| `lib/image_gateway.py` | OpenAI 兼容/自定义 JSON 图片中转站调用、异步轮询、返回图片解析 | AI 生图 | 部分属于 | 可复用 | 新流程中仅作为不合格图片后续处理，不应强制人工审核 | 图片工厂复杂队列可隐藏 | 依赖外部中转站和 Keychain；未配置时不可用 |
| `lib/text_gateway.py` | 文本本地化中转站调用，返回英/泰/越 JSON | 五国语言版本 | 旧需求为主 | 可暂停 | 新主流程暂不需要 | 隐藏 | 依赖外部接口；不属于采集箱前置必要能力 |
| `lib/keychain.py` | macOS Keychain 读写图片 API Key | 图片/文本中转站密钥 | 部分属于 | macOS 可复用 | Windows 需要替代方案 | 无 | 只支持 macOS `security` 命令 |
| `lib/prompts.py` | 内置图片生成提示词 | AI 生图 | 部分属于 | 可复用 | 新流程仅在图片不合格时使用 | 图片工厂可隐藏 | prompt 是固定模板，仍需真实中转站可用 |
| `scripts/bootstrap.py` | 创建 `data/`、logs、screenshots、images、chrome-profile、config、token | 一键启动准备 | 是 | 高 | 需保持 Windows/mac 共用 | 无 | 仅初始化目录，不做备份 |
| `scripts/real1688_search.mjs` | 通过 CDP 打开 1688 搜索页并提取卡片字段 | 真实 1688 搜索 | 是 | 中高 | 需实机回归真实 1688 DOM 和分页 | 无 | DOM 选择器和文本判断易受平台改版影响 |
| `scripts/cdp_runner.mjs` | CDP 配方执行器，支持 navigate/clickText/waitText/fill/select/upload/sleep；含旧 keyword_search 与 collection/publish 配方执行 | 妙手插件/链接采集、旧发布配方 | 部分属于 | 动作执行器可复用 | 需只允许安全采集箱动作 | 发布配方应暂停/隐藏 | clickText 依赖可见文字，配方错误可能点错；安全层需始终前置 |
| `scripts/cdp_probe.mjs` | 读取 CDP 页面标题、URL、body 文本 | 环境/登录/验证码检测 | 是 | 高 | 需控制文本截断和隐私显示 | 无 | 页面文本可能含敏感业务信息，应只展示摘要 |
| `scripts/cdp_screenshot.mjs` | CDP 截图保存到本地路径 | 失败诊断 | 是 | 高 | 需统一截图生命周期 | 无 | 截图可能包含账号/订单/店铺敏感信息 |
| `scripts/selfcheck.py` | 临时数据目录启动服务，自测 API、图片 relay、批次演练、恢复 | 本地集成自检 | 部分属于 | 可保留作回归检查 | 需新增新主流程自检版本 | 旧批次/发布演练较多 | 使用 mock relay 和本地 API，不证明真实平台可用 |
| `scripts/seed_workflow_demo.py` | 写入演示数据 | UI/流程演示 | 否 | 审计或演示可保留 | 新主流程中应隐藏 | 演示数据 | 容易被误认为真实采集结果 |
| `static/index.html` | 单页前端结构：首页、自动化控制台、环境状态、候选、图片工厂、铺货控制台、设置、弹窗 | 全部前端 | 部分属于 | 自动化控制台和环境状态可复用 | 需收缩复杂工作台 | 铺货批次、发布、五国手工配置、图片人工审核应隐藏或后置 | 当前信息量大，新用户仍会面对复杂设置 |
| `static/app.js` | 前端状态、API 调用、轮询、渲染、事件绑定、本地 token header | 全部前端交互 | 部分属于 | API 封装和自动化控制台可复用 | 需按新主流程重构视图 | 旧复杂模块仍活跃 | `browser-start` 在 CDP ready 时禁用，用户反馈“启动浏览器点不了”相关风险仍在当前分支代码中 |
| `static/styles.css` | 看板样式、响应式布局 | 前端 UI | 部分属于 | 可复用视觉基础 | 需简化为自动化控制台 | 旧工作台样式可保留但隐藏 | 小屏和直接打开 HTML 会导致体验误解 |
| `tests/**` | 单元和本地集成测试 | 后端逻辑、DB、CDP wrapper、预检、图片、标题、安全门禁、workflow | 是/部分 | 高 | 需增加真实主流程边界测试 | 部分测试服务旧批次发布 | 多数测试 patch/mock 外部平台，不能证明真实 1688/妙手闭环 |
| `run.bat` | Windows 一键启动，建 venv、装依赖、bootstrap、初始化 DB、打开 8000 | 本地启动 | 是 | 高 | 需与 README/mac 端口说明统一 | 无 | 仅 Windows；requirements 为空；真实 Chrome 仍需用户安装 |
| `启动工作台.command` | macOS 双击启动 8765 | 本地启动 | 是 | 中 | 需补 bootstrap 和端口统一 | 无 | 不创建 venv，不安装依赖，不显式运行 bootstrap |
| `requirements.txt` | Python 依赖 | 启动脚本依赖安装 | 是 | 低 | 当前为空，需明确“标准库优先” | 无 | 空文件可能让用户误以为依赖安装完成即可真实自动化 |
| `docs/local-run-guide.md` | 本地运行说明 | 一键启动、安全状态、自动化控制台 | 是 | 高 | 与审计结论同步更新 | 无 | 说明了 8000/8765 双端口，但产品入口仍不统一 |
| `docs/real-mode-safety.md` | 真实模式安全说明 | no_publish、小批量、人工验证、危险动作拦截 | 是 | 高 | 继续作为安全基线 | 无 | 文档描述的真实闭环需要实机验证支撑 |
| `docs/internal-workflow.md` | 旧 10 步上架流程状态说明 | 五国、批次、演练、发布 | 部分属于旧需求 | 可作为历史参考 | 新主流程应另写简化状态链 | 大部分偏旧复杂工作台 | 与新“不做最终发布/不做复杂工作台”定位冲突 |
| `data/config.example.json` | 本地配置示例 | 安全开关、关键词、小批量、Chrome profile | 是 | 高 | 需纳入源码或确认生成策略 | 无 | 当前在 `data/` 下，若未版本化或被忽略需确认交付方式 |
| `data/config.json` | 本地真实配置 | 本机运行状态 | 是 | 运行时文件 | 不应提交敏感配置 | 无 | 可能含用户真实关键词和路径 |
| `data/chrome-profile/` | 专用 Chrome 用户目录 | 登录态复用 | 是 | 运行时目录 | 只本机保留，不进入仓库 | 无 | 可能含 cookies/login data，审计未读取内容 |
| `data/workbench.db` | 本地 SQLite 数据 | 所有业务状态 | 是 | 运行时数据 | 需备份策略 | 无 | 真实商品、日志、截图路径和运行数据需隐私保护 |
| `data/images/`、`data/assets/`、`data/screenshots/`、`data/logs/` | 下载图、生成图、截图、日志 | 图片处理、失败诊断 | 是 | 运行时目录 | 需生命周期与备份 | 无 | 图片/截图可能含平台与店铺敏感信息 |

## 当前项目真实完成度概览

当前最成熟的能力是本地后端和 SQLite 数据层、候选/商品/图片/任务状态保存、本地配置与 `no_publish` 安全层、Workbench token 写接口保护、标题清洗、候选去重、基础风险预检、自动化日志和失败任务汇总。对应证据包括 `lib/database.py` 的完整 schema、`lib/local_config.py` 的安全门禁、`app.py` 的 `/api/automation/*`、`/api/candidates/dedupe`、`/api/candidates/precheck`、`/api/products/clean-title`、`/api/images/*` 和 `tests/test_no_publish_guard.py`、`tests/test_candidate_dedupe.py`、`tests/test_title_cleaner.py`、`tests/test_workflow.py`。

当前最不成熟的能力是真实平台端到端闭环：真实 1688 搜索、真实候选提取、真实妙手采集箱写入的代码路径已经存在，但依赖专用 Chrome/CDP、登录态、页面 DOM、妙手插件或安全配方，以及人工处理验证码/登录过期。本审计无法确认它已经能在真实 1688 与真实妙手环境稳定完成一键闭环。

当前只是界面或演示倾向较强的能力包括旧 10 步全流程上架进度、五国独立评分/定价/版本、图片工厂的人工审核、铺货批次、发布结果中心、演练/真实发布确认，以及 `scripts/seed_workflow_demo.py` 生成的演示数据。它们有代码和测试，但属于旧复杂工作台方向，不应作为新主流程第一屏能力。

当前存在但没有充分串联或没有真实验证的能力包括：1688 搜索保存候选后到妙手采集箱的全链路；妙手插件采集与链接采集兜底；图片不合格后的真实自动处理；程序重启后的真实平台断点续跑；妙手已有商品去重。`execute_pipeline_run()` 已编排新主流程，但真实外部平台部分仍是高依赖、高易变环节。

当前不能确认已经能够“一键完成真实闭环”。代码有一键入口和自动化控制台，也有 `Real1688Adapter`、`RealMiaoshouAdapter`、`collection_box_records`、运行日志和失败诊断；但真实闭环需要在已登录专用 Chrome、1688 搜索页、妙手采集箱入口、插件/配方配置均可用的环境中实测。

当前最大阻塞点是外部平台真实交互的不确定性：1688 页面 DOM、妙手页面结构、插件可用性、登录/验证码/短信验证、采集箱入口配置，以及图片自动质检准确性。其次是旧复杂工作台仍暴露，容易让第一次使用者走向五国配置、批次发布和人工审核，而不是“一次点击自动选品采集”。

值得直接保留的能力包括：`scripts/bootstrap.py` 和 `run.bat` 的本地启动准备；`lib/local_config.py` 的配置和安全开关；`BrowserManager` 的专用 Chrome/CDP 管理；`Real1688Adapter` 的真实搜索基础；`TitleCleaner`；候选去重和 `collection_box_records`；基础预检；图片下载与基础规则判断；`RealMiaoshouAdapter` 的 no_publish 保护、危险文本扫描和失败诊断；`automation_logs` 与失败处理中心。

## 审计中执行的检查

- `git status --short --branch --untracked-files=all`：开始审计时位于 `feature/00-project-audit`，未显示业务文件改动。
- `python3 -m py_compile app.py lib/*.py`：通过。
- `python3 -m unittest discover -s tests -v`：共运行 150 个测试，149 个通过，1 个失败。
- 失败用例：`tests/test_automation.py::AutomationTest.test_resolve_chrome_path_can_find_running_translocated_app`。当前机器存在 `/Applications/Google Chrome.app/...`，`resolve_chrome_path()` 优先返回固定安装路径，而测试期望返回 mocked 的 AppTranslocation 临时路径。

该失败未在本模块修复，按要求只记录为现状。
