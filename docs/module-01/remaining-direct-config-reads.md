# 尚未迁移的直接配置读取位置

审计时间：2026-06-18

本文件记录模块1第3部分后仍保留的直接读取点。原因是本段只建立兼容层，不做无边界全仓库重构。

## 统一入口

新代码应优先使用：

- `lib.local_config.get_config()`
- `lib.local_config.get_config_value(path)`
- `lib.local_config.save_config()`
- `lib.local_config.update_config()`

## 仍直接读取 settings 表的位置

| 文件 | 位置 | 当前用途 | 后续处理建议 |
| --- | --- | --- | --- |
| `app.py` | `GENERATION_SLOTS = ... DB.setting("image.concurrency")` | 图片并发槽初始化 | 模块后续将图片高级配置移入统一读取 |
| `app.py` | `evaluation.threshold/min_confidence/min_margin` 多处 | 五国评分和旧工作台评估阈值 | 旧五国流程暂保留，后续隐藏或迁移到高级配置 |
| `app.py` | `market.*.exchange/shipping_cny/platform_fee_pct/target_margin_pct` | 店铺铺货、五国价格/利润 | 属于旧铺货/五国流程，后续移出主流程 |
| `app.py` | `DB.settings()` 传给 `localize()` | 文本本地化服务配置 | 后续由统一配置和安全密钥服务组合提供 |
| `app.py` | `system_selfcheck()` 中 `automation.node_path`、采集配方、发布配方、`image.base_url` | 自检和旧高级设置 | 暂作兼容镜像，后续高级配置/开发者配置接管 |
| `lib/automation.py` | `DB.setting()` 间接读取 `automation.*` | 浏览器、插件、动作配方和发布配方 | 本段不改真实自动化动作；后续分模块替换 |
| `lib/browser_manager.py` | 通过旧兼容字段和 settings 读取 CDP/URL | 浏览器环境检测 | 后续改为 `get_config_value()` |
| `lib/image_gateway.py` | `image.*` settings | 图片服务接口协议 | 后续图片模块统一配置时迁移 |
| `lib/text_gateway.py` | `text.*` settings | 文本服务接口协议 | 后续文本/标题模块统一配置时迁移 |
| `lib/real_miaoshou_adapter.py` | `automation.*` settings | 妙手采集动作配方 | 本段禁止改真实妙手采集动作，暂保留 |

## 仍使用旧兼容别名的位置

| 文件 | 字段 | 当前用途 | 后续处理建议 |
| --- | --- | --- | --- |
| `lib/real1688_adapter.py` | `keywords`、`max_pages_per_keyword`、`max_items_per_run` | 1688 搜索关键词和小批量上限 | 后续改为 `user.keywords`、`advanced.search_max_pages`、`advanced.per_run_item_limit` |
| `lib/real_miaoshou_adapter.py` | `no_publish`、`dry_run_collect`、`collect_to_box_only` | 妙手采集前安全校验 | 后续改为 `user.run_mode` 与 `advanced.no_publish/collect_to_box_only` |
| `lib/automation.py` | `dry_run_collect`、`no_publish`、`chrome_profile_dir` | 旧自动化控制和安全保护 | 后续按自动化模块拆迁 |
| `lib/browser_manager.py` | `chrome_debug_port` | CDP 端口兼容读取 | 后续改为 `advanced.cdp_port` |
| `app.py` | `chrome_debug_port`、`chrome_profile_dir`、`no_publish` | settings 镜像和发布安全拦截 | 已有统一配置兼容桥，后续逐步替换 |

## 直接文件或环境读取

| 文件 | 读取内容 | 当前用途 | 处理 |
| --- | --- | --- | --- |
| `app.py` | `WORKBENCH_DATA_DIR`、`HOST`、`PORT` | 本地服务路径与监听地址 | 属于运行环境，不含敏感业务配置，暂保留 |
| `scripts/seed_workflow_demo.py` | `WORKBENCH_DATA_DIR` | 演示数据脚本 | 旧演示脚本，后续隔离 |
| `scripts/selfcheck.py` | `WORKBENCH_DATA_DIR`、`PORT` | 自检脚本 | 暂保留 |
| `scripts/bootstrap.py` | `data/config.json` 路径输出 | 启动提示 | 使用 `ensure_local_runtime()`，不另建默认配置 |

## 当前结论

模块1第3部分后，新配置文件是主配置来源，settings 表是兼容镜像。仍保留的直接读取集中在旧五国评分、图片服务、自动化动作配方和自检区域，不应在普通主流程继续扩展这些入口。
