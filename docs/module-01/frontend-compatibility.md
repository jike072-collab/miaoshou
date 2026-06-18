# Module 01 前端配置兼容说明

本文件记录模块1第4部分对现有前端的最小兼容改动。目标是让现有设置页能读取和保存统一配置，不重做页面、不改真实自动化动作。

## 修改位置

| 文件 | 修改内容 |
| --- | --- |
| `static/index.html` | 在设置页增加 `#user-config-settings` 基础任务配置表单 |
| `static/app.js` | `loadAll()` 增加读取 `/api/config`；新增基础配置填表、保存和错误展示；旧设置表单保留 |

## 新增基础配置表单

表单 ID：

```text
user-config-settings
```

保存接口：

```text
PUT /api/config
```

保存 payload：

```json
{
  "values": {
    "category": "鞋类",
    "keywords": ["运动鞋", "凉鞋"],
    "target_count": 50,
    "candidate_limit": 200,
    "purchase_price_min": 0,
    "purchase_price_max": 200,
    "max_weight_kg": 2,
    "minimum_profit_margin": 0.2,
    "auto_season_check": true,
    "image_strategy": "inspect_and_fix",
    "run_mode": "simulation"
  }
}
```

## 前端字段映射

| 前端字段 | 新配置字段 | 单位/转换 |
| --- | --- | --- |
| `category` | `user.category` | 字符串，后端去除首尾空格 |
| `keywords` | `user.keywords` | textarea，按换行、英文逗号、中文逗号拆分 |
| `target_count` | `user.target_count` | 整数 |
| `candidate_limit` | `user.candidate_limit` | 整数 |
| `purchase_price_min` | `user.purchase_price_min` | 人民币元，数字 |
| `purchase_price_max` | `user.purchase_price_max` | 人民币元，数字 |
| `max_weight_kg` | `user.max_weight_kg` | 公斤，数字 |
| `minimum_profit_margin` | `user.minimum_profit_margin` | 小数，`0.2` 表示 20% |
| `auto_season_check` | `user.auto_season_check` | checkbox 布尔值 |
| `image_strategy` | `user.image_strategy` | `original` / `inspect_and_fix` / `regenerate` |
| `run_mode` | `user.run_mode` | `simulation` / `collect_to_box` |

## 旧字段兼容

旧 `/api/settings` 表单仍存在：

- `#image-settings`
- `#automation-settings`
- `#evaluation-settings`

旧表单继续提交：

```text
POST /api/settings
```

其中 `automation.mode` 的页面选项已改为：

- `simulation`：模拟运行
- `collect_to_box`：采集到妙手采集箱

后端兼容层仍会同步旧业务需要的 `automation.mode`：

- `simulation` -> `dry_run`
- `collect_to_box` -> `live`

这里的 `live` 只作为旧 `AutomationEngine` 的兼容值，不代表允许最终发布。发布安全仍由 `no_publish=true` 和 `collect_to_box_only=true` 强制保护。

## 错误和警告展示

前端新增：

- `formatApiIssues()`
- `#user-config-message`

当 `/api/config` 返回：

```json
{
  "ok": false,
  "errors": [
    {"field": "user.target_count", "message": "必须是1至500之间的整数"}
  ]
}
```

页面会把错误显示在基础配置表单附近，并通过 toast 提醒。

## 重复保存保护

已实现：

- 基础配置保存中禁用提交按钮。
- 旧三张 settings 表单保存中禁用提交按钮。
- 保存失败后恢复按钮。
- 保存成功后重新加载配置和 settings。

## 运行模式展示

普通配置页面只显示：

- 模拟运行
- 采集到妙手采集箱

本段未新增：

- 正式发布开关
- 自动上架开关
- 跳过发布安全检查开关
- 保存账号密码或 Cookie 的入口

## 尚未迁移位置

以下属于旧范围或后续模块，不在本段重做：

- 铺货控制台旧页面仍存在。
- 发布结果中心旧页面仍存在。
- 批次、店铺、五国版本相关 UI 仍存在。
- 大量旧业务逻辑仍直接读取 `DB.setting()`。
- 前端还会读取 `/api/settings` 来填充图片、自动化和评估表单。

这些位置已在 `docs/module-01/remaining-direct-config-reads.md` 和模块0范围收缩文档中继续跟踪。
