# 旧配置映射表

本文件记录旧版平铺配置、旧 settings 表和新配置结构之间的映射。当前主实现位于 `lib/local_config.py`。

| 旧字段 | 旧来源 | 新字段 | 转换规则 | 默认值 | 是否废弃 |
| --- | --- | --- | --- | --- | --- |
| `category` | 旧 config.json / 前端 | `user.category` | 去首尾空格，保留文本 | `鞋类` | 否 |
| `keywords` | 旧 config.json / 前端 / settings 旧输入 | `user.keywords` | 字符串拆分为数组，去空、去重 | `["运动鞋", "透气鞋", "凉鞋", "防滑鞋"]` | 否 |
| `target_count` | 旧 config.json | `user.target_count` | 转为整数 | `50` | 否 |
| `max_items_per_run` | 旧 config.json / app 默认值 | `advanced.per_run_item_limit` | 转为整数并限制安全上限 | `10` | 旧字段废弃，兼容保留 |
| `candidate_limit` | 旧 config.json / 前端 | `user.candidate_limit` | 转为整数，且不小于 `target_count` | `200` | 否 |
| `purchase_price_min` | 旧 config.json | `user.purchase_price_min` | 转为数字，单位人民币元 | `0` | 否 |
| `purchase_price_max` | 旧 config.json | `user.purchase_price_max` | 转为数字，单位人民币元 | `200` | 否 |
| `max_weight_kg` | 新 config / 旧迁移目标 | `user.max_weight_kg` | 直接保留公斤单位 | `2` | 否 |
| `max_weight_g` | 旧 config.json / 旧数据 | `user.max_weight_kg` | 除以 1000 转为公斤 | `1.5` 示例 | 旧字段废弃，兼容保留 |
| `minimum_profit_margin` | 旧 config.json | `user.minimum_profit_margin` | 小数化，`0.2` 表示 20% | `0.2` | 否 |
| `min_profit_margin` | 旧 settings / 旧页面 | `user.minimum_profit_margin` | 100 以内视为百分比，除以 100 | `0.2` | 旧字段废弃，兼容保留 |
| `market.target_margin_pct` | 旧 settings | `user.minimum_profit_margin` | 除以 100 | `0.2` | 旧字段废弃，兼容保留 |
| `auto_season_check` | 旧 config.json | `user.auto_season_check` | 转为布尔值 | `true` | 否 |
| `image_strategy` | 旧 config.json / 页面 | `user.image_strategy` | `original` / `inspect_and_fix` / `regenerate` | `inspect_and_fix` | 否 |
| `enable_image_check` | 旧 config.json / settings | `advanced.image_inspection_enabled` | 转为布尔值 | `true` | 否 |
| `dry_run_collect` | 旧 config.json | `user.run_mode` | `true` -> `simulation` | `simulation` | 旧字段废弃，兼容保留 |
| `collect_to_box_only` | 旧 config.json | `user.run_mode` | `true` 且 `dry_run_collect=false` -> `collect_to_box` | `collect_to_box` | 旧字段废弃，兼容保留 |
| `mode` | 旧 config.json | `user.run_mode` | `mock/dry_run/simulation` -> `simulation`；`real/collect_to_box` -> `collect_to_box`；`publish` 被拒绝降级 | `simulation` | 旧字段废弃，兼容保留 |
| `real_mode` | 旧页面/配置 | `user.run_mode` | 含义不明确，默认 `simulation` | `simulation` | 是 |
| `live_mode` | 旧页面/配置 | `user.run_mode` | 含义不明确，默认 `simulation` | `simulation` | 是 |
| `publish_enabled` | 旧页面/配置 | `legacy.flat.publish_enabled` | 强制拒绝，不生成发布模式 | `false` | 是 |
| `no_publish` | 旧 config.json / settings 安全开关 | `advanced.no_publish` | 强制保持 `true` | `true` | 否 |
| `chrome_path` | 旧 settings / 旧页面 | `advanced.browser_path` | 路径标准化 | 空 | 旧字段废弃，兼容保留 |
| `chrome_profile_dir` | 旧 config.json / settings | `advanced.browser_user_data_dir` | 路径标准化 | `data/chrome-profile` | 否 |
| `chrome_debug_port` | 旧 config.json / settings | `advanced.cdp_port` | 转为端口号 | `9222` | 否 |
| `automation.chrome_path` | 旧 settings | `advanced.browser_path` | 路径标准化 | 空 | 旧字段废弃 |
| `automation.chrome_profile_dir` | 旧 settings | `advanced.browser_user_data_dir` | 路径标准化 | `data/chrome-profile` | 否 |
| `automation.cdp_port` | 旧 settings | `advanced.cdp_port` | 转为端口号 | `9222` | 否 |
| `automation.alibaba_url` | 旧 settings | `advanced.alibaba_url` | URL 校验 | `https://www.1688.com/` | 否 |
| `automation.miaoshou_url` | 旧 settings | `advanced.miaoshou_url` | URL 校验 | `https://erp.91miaoshou.com/` | 否 |
| `automation.plugin_extension_id` | 旧 settings / 插件设置 | `advanced.plugin_id` | 字符串保留 | 空 | 旧字段废弃，兼容保留 |
| `max_retry` | 旧 config.json / settings | `advanced.step_retry_count` | 转为整数 | `2` | 旧字段废弃，兼容保留 |
| `image.timeout` | 旧 settings | `advanced.image_service_timeout_seconds` | 转为秒 | `30` | 旧字段废弃，兼容保留 |
| `image.base_url` | 旧 settings | `advanced.image_service_url` | URL 校验 | 空 | 旧字段废弃，兼容保留 |
| `image.request_template` | 旧 settings | legacy | 原样保留，不进入普通配置 | 旧模板 | 旧字段保留 |
| `image.retries` | 旧 settings | `advanced.step_retry_count` | 转为整数 | `2` | 旧字段废弃，兼容保留 |
| `market.*.exchange` | 旧 settings | legacy | 原样保留 | 旧汇率 | 旧字段保留 |
| `market.*.shipping_cny` | 旧 settings | legacy | 原样保留 | 旧运费 | 旧字段保留 |
| `evaluation.*` | 旧 settings | legacy | 原样保留 | 旧评分规则 | 旧字段保留 |
