# 🍔 麦当劳优惠券自动领取 (MCD Auto Claim)

基于 MCP (Model Context Protocol) 的麦当劳优惠券自动领取工具，支持 GitHub Actions 自动调度和 Telegram 通知。

## ✨ 功能特点

- 📅 **每月自动获取活动日历** - 每月1日自动获取本月所有活动
- 🎟️ **智能领券** - 根据活动日期自动领取优惠券
- 📱 **Telegram 通知** - 实时推送领券结果到 Telegram
- 🌐 **GitHub Pages 报告** - 自动生成并部署可视化报告
- ⏰ **北京时间调度** - 按北京时间执行，活动日凌晨自动触发

## 🚀 快速开始

### 1. Fork 本仓库

点击右上角的 Fork 按钮，将仓库 Fork 到你的账号下。

### 2. 配置 Secrets

在仓库的 `Settings` -> `Secrets and variables` -> `Actions` 中添加以下 Secrets：

| Secret 名称 | 说明 | 必需 |
|------------|------|------|
| `MCD_TOKEN` | 麦当劳 MCP Token | ✅ |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | ✅ |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | ✅ |

### 3. 配置 Variables（可选）

在 `Settings` -> `Secrets and variables` -> `Actions` -> `Variables` 中添加：

| Variable 名称 | 说明 | 必需 |
|--------------|------|------|
| `GITHUB_PAGES_URL` | 自定义 GitHub Pages 地址 | ❌ (可选) |

> 💡 **提示**：如果不配置 `GITHUB_PAGES_URL`，脚本会自动从 `GITHUB_REPOSITORY` 环境变量生成 URL，格式为 `https://<owner>.github.io/<repo>/`

### 4. 启用 GitHub Pages

1. 进入 `Settings` -> `Pages`
2. Source 选择 `GitHub Actions`

### 5. 启用 Actions

1. 进入 `Actions` 标签页
2. 点击 "I understand my workflows, go ahead and enable them"


## ⏰ 自动调度

GitHub Actions 会在以下时间自动执行：

- **每月1日 00:05 (北京时间)** - 获取本月活动日历
- **每天 00:05 (北京时间)** - 检查是否有活动，有则自动领券

> 注意：GitHub Actions 使用 UTC 时间，北京时间 00:05 = UTC 16:05（前一天）


## 📱 Telegram 通知示例
```
🍔 *麦当劳优惠券自动领取报告*
⏰ `2026-01-17 08:05:00`

📊 *数据概览*
• 本月活动: 15 个
• 可用优惠券: 12 张
• 新领取: 3 张

📅 *近期活动*

*2026-01-17* (2个)
  • 10块麦乐鸡特惠
  • 薯条买一送一

🎟️ *我的优惠券* (12张)

💵 *超值优惠 (<10元)*
• ¥9.9 10块麦乐鸡 (01-17 至 01-18)

💰 *实惠套餐 (10-20元)*
• ¥13.5 中薯条买一送一 (01-19 至 01-23)

🔗 [查看详情] 
```

## 📁 项目结构

```
mcd-actions/
├── auto_claim.py              # 主脚本
├── calendar_data.json         # 活动日历数据（自动生成）
├── index.html                 # 报告页面（自动生成）
├── README.md                  # 说明文档
└── .github/
    └── workflows/
        └── mcd-auto-claim.yml # GitHub Actions 工作流
```

## 🔒 获取 Token

### MCD Token
见麦当劳开发者文档`https://open.mcd.cn/mcp/doc`。

### Telegram Bot Token

1. 在 Telegram 中找到 @BotFather
2. 发送 `/newbot` 创建机器人
3. 获取 Bot Token

### Telegram Chat ID

1. 向你的 Bot 发送任意消息
2. 访问 `https://api.telegram.org/bot<YourBOTToken>/getUpdates`
3. 找到 `chat.id` 字段


## 📄 License

MIT License
