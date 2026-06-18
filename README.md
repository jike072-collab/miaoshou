# 妙手智能选品工作台

面向 TikTok Shop 东南亚五国店群的本地选品、AI 图片和妙手 ERP 自动化控制台。

## 已实现

- 1688 链接候选批量导入，一次最多 200 个
- 运动鞋、运动包、运动套装供应数据管理
- 马来西亚、菲律宾、新加坡、泰国、越南独立评分
- 70 分自动采集门槛、70% 最低置信度、20% 最低毛利率
- 缺少真实市场样本时自动转人工确认
- 侵权、资质、亏损、物流和 SKU 硬性拦截
- 妙手插件优先、链接采集兜底的任务状态机
- SQLite 本地数据库及旧 `products.json` 自动迁移
- OpenAI 兼容及自定义 JSON 图片中转站
- 可配置生图并发、失败重试，任务和提示词支持服务重启后自动恢复
- 内置鞋、包、运动套装 GPT Image 严格保真提示词
- 基础、标准、详情和自定义生图档位
- 图片人工审核门禁
- 五国店铺配置、50 款 × 20 店铺批次限制
- 发布演练、人工确认、任务重试和幂等数据结构
- macOS Keychain 保存图片 API Key
- 页面加载时自动运行数据库、目录、Node、Chrome、配方和中转站自检
- 拒绝非本机网页跨域调用本地写接口

## 启动

macOS 可双击 `启动工作台.command`，也可以运行：

```bash
python3 app.py
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。除正版 Chrome 和妙手官方插件外，后端不需要安装第三方 Python 包。

数据保存在 `data/workbench.db`，图片保存在 `data/assets/`。

## 本地配置

示例配置位于 `data/config.example.json`。首次使用可复制为本机配置：

```bash
cp data/config.example.json data/config.json
```

`data/config.json` 已被 Git 忽略，用于保存本机关键词、采集数量、价格范围、重量、利润率和运行模式等配置。程序启动时如果发现配置不存在，会自动创建安全默认配置；如果配置 JSON 损坏，会备份损坏文件并加载安全默认值。

普通用户主要配置：

- 商品类目；
- 搜索关键词；
- 目标采集数量和候选商品上限；
- 采购价格范围，单位为人民币元；
- 最大重量，单位为公斤；
- 最低利润率，`0.2` 表示 20%；
- 是否自动判断季节；
- 图片处理策略；
- 运行模式。

当前运行模式只有两种：

- `simulation`：模拟运行，不执行妙手真实采集；
- `collect_to_box`：只采集到妙手采集箱，不执行最终发布。

当前版本不支持自动发布，不提供保存 1688 或妙手密码、Cookie、token 的配置项。详细字段见 `docs/module-01/config-reference.md`。

## 首次配置

1. 安装正版 Google Chrome。
2. 安装最新版妙手跨境 ERP 助手插件。
3. 在妙手中授权 1688 货源账号和 TikTok Shop 店铺。
4. 打开“系统设置”，填写 Chrome 路径和图片中转站。
5. 保持 `simulation`，先完成候选评估和测试批次。
6. 在专用 Chrome 中登录妙手和 1688。
7. 在自动化设置中录入采集箱认领配方，完整自检通过后再切换 `collect_to_box`。

工作台优先使用 `/Applications/Google Chrome.app`，也能识别当前正在运行的 Chrome 临时路径。若 Chrome 从 macOS `AppTranslocation` 临时路径运行，建议将应用移动到 `/Applications`，避免重启后路径变化。专用 Chrome 会同时打开扩展管理、妙手和 1688 页面；首次使用需在专用 Chrome 的扩展页手动加载妙手插件解压目录，然后完成登录。

动作配方使用 JSON 数组，支持 `navigate`、`clickText`、`waitText`、`assertText`、`fill`、`select`、`upload` 和 `sleep`。字段值可使用 `{{title}}`、`{{price}}`、`{{warehouse}}`、`{{inventory}}`、`{{shopName}}`、`{{sku}}`、`{{category}}`、`{{weightG}}`、`{{lengthCm}}`、`{{widthCm}}`、`{{heightCm}}` 和 `{{image1}}` 等批次变量。店铺售价系数会在传入 `{{price}}` 前应用。发布动作使用 `phase: "prepare"` 或 `phase: "confirm"` 区分发布前填写与最终确认。

采集优先点击1688页面中的妙手官方插件。若插件按钮或成功提示未找到，并且已配置“链接采集兜底配方”，系统会自动切换到妙手链接采集，然后继续执行采集箱认领配方。任务最多自动重试2次，超过限制后必须先修复登录、插件或页面配方。

## 评估规则

每个国家按以下权重计算：

| 维度 | 权重 |
| --- | ---: |
| 90 天趋势 | 20% |
| 当地销量与评价 | 15% |
| 预计利润 | 25% |
| 竞争强度 | 15% |
| 重量与物流 | 10% |
| 供应稳定性 | 10% |
| 图片与内容 | 5% |

没有真实市场样本、类目未识别、SKU 不完整或存在硬性风险时不会自动进入妙手采集。

## 图片中转站

OpenAI 兼容模式默认调用：

```text
POST {Base URL}/v1/images/edits
Authorization: Bearer {API Key}
model=gpt-image-1
image=<商品参考图>
prompt=<内置严格保真提示词>
```

自定义 JSON 模式支持配置请求模板，模板变量包括 `{{model}}`、`{{prompt}}` 和 `{{image_base64}}`。可填写图片响应路径；若接口返回异步任务ID，还可配置任务ID路径、查询路径和状态路径自动轮询。接口返回应包含以下任一结构：

```json
{"data":[{"b64_json":"..."}]}
```

```json
{"images":[{"url":"https://..."}]}
```

## 主要接口

- `POST /api/candidates/import-links`
- `POST /api/candidates/search`
- `POST /api/candidates/evaluate`
- `POST /api/candidates/collect-qualified`
- `POST /api/images/generate`
- `POST /api/images/{id}/approve`
- `POST /api/shops`
- `POST /api/batches`
- `POST /api/batches/{id}/prepare`
- `POST /api/batches/{id}/confirm`
- `POST /api/runs/{id}/retry`
- `GET /api/automation/preflight`

## 测试

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile app.py lib/*.py
python3 scripts/selfcheck.py
```

## 安全边界

- 不保存妙手或 1688 密码、Cookie、短信验证码。
- 不修改或逆向妙手官方插件。
- CAPTCHA、短信验证、登录失效和页面结构不匹配时必须暂停。
- 默认 `simulation`，当前版本只允许进入妙手采集箱，不执行最终发布。
- 不处理仿品、授权不明品牌或需要特殊资质的商品。
