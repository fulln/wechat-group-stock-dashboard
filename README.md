# WeChat Group Stock Dashboard

Turn a WeChat-style group chat markdown export into a static stock dashboard.

中文文档：[README.zh-CN.md](README.zh-CN.md)

This project was extracted from a private local workflow and cleaned up for
reuse. It focuses on four things:

- stock mention detection
- group sentiment, sector, and market-context summaries
- Google Finance quote snapshots by default
- intraday and speaker-centric charts by default

It does not require a server. The output is static HTML/JSON that can be opened
locally or hosted on any static host. Cloudflare Pages deployment is optional.

> This project is for personal data analysis and research. It is not financial
> advice.

## Input Format

The parser expects markdown shaped like this:

```markdown
# 聊天记录: My Group

**消息数量:** 3

- [2026-07-17 09:31] Alice: 长电今天很强
- [2026-07-17 10:02] Bob: 通富微电又跌了
- [2026-07-17 10:10] me: 福达合金看看
```

`wechat-cli export --format markdown` produces compatible output, but the code
does not depend on a specific exporter as long as the lines follow the timestamp
format above.

## Quick Start

Install the local Python environment, build the sample dashboard, and open the
generated static HTML:

```bash
./start.sh
```

Use your own chat export:

```bash
./start.sh --chat-md /path/to/chat.md
```

Useful variants:

```bash
./start.sh --chat-md /path/to/chat.md --no-market-data
./start.sh --chat-md /path/to/chat.md --market-channel sina
./start.sh --group-name "My Group"
./start.sh --install-wechat-cli --setup-only
./start.sh --install-skill
```

The generated page is `exports/group_stock_dashboard/index.html`. No server is
started; the script opens the static file when possible.

## Manual Build

```bash
python3 build_stock_mentions.py examples/sample_chat.md \
  --html exports/sample/index.html \
  --json exports/sample/stock_mentions.json \
  --markdown exports/sample/stock_mentions.md \
  --no-google-finance
```

Open `exports/sample/index.html` in a browser.

Or use the build wrapper directly. It fetches market snapshots, intraday lines, and
speaker-page daily K data by default. Snapshot channel `auto` keeps Google
Finance as the primary source and falls back to Sina quote when needed:

```bash
CHAT_MD=examples/sample_chat.md ./scripts/one_click_deploy.sh
```

## Skip Market Data

```bash
CHAT_MD=/path/to/chat.md ./scripts/one_click_deploy.sh --no-market-data
```

The speaker page is still generated in this mode, but its daily K data is
marked as disabled.

To force a snapshot channel:

```bash
MARKET_DATA_CHANNEL=google CHAT_MD=/path/to/chat.md ./scripts/one_click_deploy.sh
MARKET_DATA_CHANNEL=sina CHAT_MD=/path/to/chat.md ./scripts/one_click_deploy.sh
```

You can also run the market-data steps individually:

```bash
python3 fetch_google_finance_snapshot.py \
  exports/sample/stock_mentions.json \
  --output exports/sample/google_finance_snapshot.json \
  --channel auto

python3 fetch_stock_trends.py \
  exports/sample/stock_mentions.json \
  --output exports/sample/stock_trends.json

python3 build_stock_mentions.py examples/sample_chat.md \
  --html exports/sample/index.html \
  --json exports/sample/stock_mentions.json \
  --markdown exports/sample/stock_mentions.md \
  --google-finance exports/sample/google_finance_snapshot.json \
  --stock-trends exports/sample/stock_trends.json
```

Google Finance and Sina quote endpoints are unofficial scraping sources here;
they can change or rate-limit. Cache outputs when possible.

## Speaker Dashboard

After you have multiple daily folders like:

```text
exports/group_stock_dashboard/2026-07-15/stock_mentions.json
exports/group_stock_dashboard/2026-07-16/stock_mentions.json
```

build the speaker-centric page:

```bash
python3 build_speaker_stock_dashboard.py \
  --input-dir exports/group_stock_dashboard \
  --output exports/group_stock_dashboard/speakers.html \
  --json exports/group_stock_dashboard/speakers.json \
  --daily-k exports/group_stock_dashboard/speaker_daily_k.json \
  --days 15
```

## Daily Pipeline

If you use `wechat-cli`, set the group name and run the daily script:

```bash
WECHAT_GROUP_NAME="My Group" ./scripts/daily_group_stock_dashboard.sh
```

`./start.sh --group-name "My Group"` checks for `wechat-cli` automatically. If
it is missing, the script installs `@canghe_ai/wechat-cli` locally under
`.tools/` and passes that binary to the export step. Override the npm package
with `WECHAT_CLI_PACKAGE=...` if you need a different source. To install it
without building a dashboard:

```bash
./start.sh --install-wechat-cli --setup-only
```

The script writes to `exports/group_stock_dashboard/YYYY-MM-DD/`, updates
`page_history.json`, refreshes `index.html`, and builds `speakers.html`. It
fetches market snapshots, intraday lines, and speaker-page daily K data by
default. `MARKET_DATA_CHANNEL=auto` uses Google Finance first and Sina quote as
fallback. Add `--no-market-data` for a lightweight/offline run.

To display exported sender `me` as another name:

```bash
CHAT_STOCK_SELF_NAME="your-name" WECHAT_GROUP_NAME="My Group" \
  ./scripts/daily_group_stock_dashboard.sh
```

## Optional Cloudflare Pages

Install and log in to Wrangler first:

```bash
npm install -g wrangler
wrangler login
```

Then deploy:

```bash
CF_PAGES_PROJECT_NAME=group-stock-dashboard \
CHAT_MD=/path/to/chat.md \
./scripts/one_click_deploy.sh --deploy --create-project
```

Add `--no-market-data` when you want to deploy without Google Finance, intraday
chart data, or speaker-page daily K data:

```bash
CHAT_MD=/path/to/chat.md ./scripts/one_click_deploy.sh --no-market-data --deploy
```

Backfill gently:

```bash
WECHAT_GROUP_NAME="My Group" \
./scripts/backfill_group_stock_dashboard.sh --days 15 --sleep-seconds 600 --deploy
```

Add `--no-market-data` when you want to skip Google Finance, intraday snapshots,
and speaker-page daily K data for each day.

## Configure Stocks

The stock dictionary and sector rules currently live in
`build_stock_mentions.py`:

- `STOCKS`
- `SECTOR_RULES`
- `BULLISH_WORDS`
- `BEARISH_WORDS`
- `MARKET_WORDS`

The included dictionary is intentionally small and opinionated. Extend it for
your own market universe before relying on the output.

## Customize The Pages

The generated files remain standalone static HTML, but the source UI is split
into templates:

- `templates/stock_mentions.html`
- `templates/stock_mentions.js`
- `templates/speaker_dashboard.html`
- `templates/speaker_dashboard.js`

Python scripts only inject escaped page metadata and JSON data into these
templates. Edit the template files when changing layout, CSS, or browser-side
interactions.

## Privacy

Never commit `exports/`, logs, `.env`, or raw chat exports. They are ignored by
default. See `PRIVACY.md`.

## License

MIT
