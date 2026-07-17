# 微信群聊股票看板

把微信群聊 markdown 导出文件转换成一个静态股票分析页面。

这个仓库只做本地分析和静态页面生成，不需要启动服务。Cloudflare Pages
部署是可选项。

> 仅用于个人复盘和研究，不构成投资建议。

## 功能

- 标记群里出现的股票
- 统计股票、情绪、板块、大盘相关讨论
- 可选抓取 Google Finance 快照
- 可选抓取 A 股分时线，并把群聊发言标在折线上
- 生成人物维度页面：按发言人查看提到过的股票和日 K
- 可选发布到 Cloudflare Pages

## 输入格式

支持类似下面的 markdown：

```markdown
# 聊天记录: 示例股票交流群

**消息数量:** 3

- [2026-07-17 09:31] Alice: 长电今天很强
- [2026-07-17 10:02] Bob: 通富微电又跌了
- [2026-07-17 10:10] me: 福达合金看看
```

如果你用 `wechat-cli export --format markdown` 导出，格式通常可以直接使用。

## 最快体验

不抓行情，只用示例聊天生成页面：

```bash
CHAT_MD=examples/sample_chat.md ./scripts/one_click_deploy.sh --no-market-data
```

输出：

```text
exports/group_stock_dashboard/index.html
```

直接用浏览器打开即可。

## 从已有聊天导出生成完整看板

```bash
CHAT_MD=/path/to/chat.md ./scripts/one_click_deploy.sh
```

这会执行：

1. 识别股票并生成基础 JSON
2. 抓 Google Finance 快照
3. 抓分时图
4. 生成最终 HTML
5. 更新历史记录
6. 生成发言人股票图谱

## 从 wechat-cli 直接导出

```bash
WECHAT_GROUP_NAME="你的群名" ./scripts/one_click_deploy.sh
```

如果想把导出的 `me` 显示成自己的名字：

```bash
CHAT_STOCK_SELF_NAME="your-name" \
WECHAT_GROUP_NAME="你的群名" \
./scripts/one_click_deploy.sh
```

## 一键部署到 Cloudflare Pages

先安装并登录 Wrangler：

```bash
npm install -g wrangler
wrangler login
```

首次创建项目并发布：

```bash
CHAT_MD=/path/to/chat.md \
CF_PAGES_PROJECT_NAME=group-stock-dashboard \
./scripts/one_click_deploy.sh --deploy --create-project
```

之后发布：

```bash
CHAT_MD=/path/to/chat.md ./scripts/one_click_deploy.sh --deploy
```

也可以通过群名导出并部署：

```bash
WECHAT_GROUP_NAME="你的群名" ./scripts/one_click_deploy.sh --deploy
```

## 回填最近 15 天

默认每天之间间隔 10 分钟，避免对本地导出和行情接口太激进：

```bash
WECHAT_GROUP_NAME="你的群名" \
./scripts/backfill_group_stock_dashboard.sh --days 15 --deploy
```

先看会跑哪些日期：

```bash
WECHAT_GROUP_NAME="你的群名" \
./scripts/backfill_group_stock_dashboard.sh --days 15 --dry-run
```

## 自定义股票词典

目前股票词典在 `build_stock_mentions.py` 里：

- `STOCKS`
- `SECTOR_RULES`
- `BULLISH_WORDS`
- `BEARISH_WORDS`
- `MARKET_WORDS`

这是一个小而偏手工的词典。开源版默认不会覆盖全部 A 股、港股、美股简称。
如果你要用于自己的群，建议先补充常见简称。

## Codex Skill

仓库里带了一个可选 Skill：

```text
codex-skill/wechat-group-stock-dashboard/
```

安装方式示例：

```bash
mkdir -p ~/.codex/skills
cp -R codex-skill/wechat-group-stock-dashboard ~/.codex/skills/
```

之后可以直接让 Codex 使用这个 skill 来生成或部署群聊股票看板。

## 隐私

不要提交：

- `exports/`
- 原始聊天记录
- `.env`
- Cloudflare token
- 日志

这些默认都已经在 `.gitignore` 里。
