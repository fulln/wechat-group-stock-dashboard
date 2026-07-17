#!/usr/bin/env bash
# Daily pipeline:
#   1. export today's WeChat group messages
#   2. detect mentioned stocks
#   3. optionally fetch Google Finance and intraday market snapshots
#   4. rebuild the static dashboard
#   5. optionally deploy to Cloudflare Pages

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/exports/group_stock_dashboard}"
LOG_DIR="$ROOT/logs"
mkdir -p "$OUT_DIR" "$LOG_DIR"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

GROUP_NAME="${WECHAT_GROUP_NAME:-${GROUP_NAME:-}}"
RUN_DATE="${RUN_DATE:-$(date +%F)}"
RUN_VERSION="${RUN_VERSION:-$(date +%Y%m%d%H%M%S)}"
PROJECT_NAME="${CF_PAGES_PROJECT_NAME:-group-stock-dashboard}"
BRANCH="${CF_PAGES_BRANCH:-main}"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi
WECHAT_BIN="${WECHAT_BIN:-wechat-cli}"
WRANGLER_BIN="${WRANGLER_BIN:-$(command -v wrangler || true)}"
WITH_MARKET_DATA="${WITH_MARKET_DATA:-0}"

DATED_DIR="$OUT_DIR/$RUN_DATE"
mkdir -p "$DATED_DIR"

CHAT_MD="$DATED_DIR/chat.md"
STOCK_HTML="$DATED_DIR/index.html"
STOCK_JSON="$DATED_DIR/stock_mentions.json"
STOCK_MD="$DATED_DIR/stock_mentions.md"
GF_JSON="$DATED_DIR/google_finance_snapshot.json"
TRENDS_JSON="$DATED_DIR/stock_trends.json"
HISTORY_JSON="$OUT_DIR/page_history.json"
CURRENT_HTML="$OUT_DIR/stock_mentions.html"
CURRENT_INDEX="$OUT_DIR/index.html"
REDIRECTS_FILE="$OUT_DIR/_redirects"
SPEAKERS_HTML="$OUT_DIR/speakers.html"
SPEAKERS_JSON="$OUT_DIR/speakers.json"
SPEAKER_DAILY_K="$OUT_DIR/speaker_daily_k.json"
DATED_HTML="$OUT_DIR/${RUN_DATE}.html"

DO_DEPLOY=0
CREATE_PROJECT=0
for arg in "$@"; do
  case "$arg" in
    --deploy) DO_DEPLOY=1 ;;
    --create-project) CREATE_PROJECT=1 ;;
    --with-market-data) WITH_MARKET_DATA=1 ;;
    --no-market-data) WITH_MARKET_DATA=0 ;;
    --help|-h)
      cat <<EOF
Usage: $0 [--with-market-data] [--deploy] [--create-project] [--no-market-data]

Environment:
  WECHAT_GROUP_NAME        required group name for wechat-cli export
  OUT_DIR                  default: ./exports/group_stock_dashboard
  RUN_DATE                 default: today, YYYY-MM-DD
  WITH_MARKET_DATA         default: 0; set 1 to fetch Google Finance and intraday data
  CHAT_STOCK_SELF_NAME     optional display name for exported sender "me"
  CF_PAGES_PROJECT_NAME    default: group-stock-dashboard
  CF_PAGES_BRANCH          default: main
  CLOUDFLARE_API_TOKEN     required by wrangler in non-interactive runs
EOF
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ -z "$GROUP_NAME" ]]; then
  echo "WECHAT_GROUP_NAME is required when exporting with wechat-cli." >&2
  echo "Example: WECHAT_GROUP_NAME='My Group' $0" >&2
  exit 2
fi

echo "==> $(date '+%F %T') export WeChat group: $GROUP_NAME / $RUN_DATE"
"$WECHAT_BIN" export "$GROUP_NAME" \
  --start-time "$RUN_DATE" \
  --end-time "$RUN_DATE" \
  --limit 10000 \
  --format markdown \
  --output "$CHAT_MD"

echo "==> build stock list without stale Google Finance data"
"$PYTHON_BIN" "$ROOT/build_stock_mentions.py" "$CHAT_MD" \
  --html "$STOCK_HTML" \
  --json "$STOCK_JSON" \
  --markdown "$STOCK_MD" \
  --no-google-finance

if [[ "$WITH_MARKET_DATA" -eq 1 ]]; then
  echo "==> fetch Google Finance snapshot"
  "$PYTHON_BIN" "$ROOT/fetch_google_finance_snapshot.py" "$STOCK_JSON" --output "$GF_JSON"

  echo "==> fetch stock intraday trends"
  "$PYTHON_BIN" "$ROOT/fetch_stock_trends.py" "$STOCK_JSON" --output "$TRENDS_JSON"
else
  echo "==> skip Google Finance and intraday data (pass --with-market-data to enable)"
fi

echo "==> update page history"
"$PYTHON_BIN" "$ROOT/update_page_history.py" \
  --history "$HISTORY_JSON" \
  --date "$RUN_DATE" \
  --href "${RUN_DATE}/" \
  --title "$GROUP_NAME" \
  --stock-json "$STOCK_JSON" \
  --version "$RUN_VERSION"

echo "==> rebuild final dashboard"
final_args=(
  "$ROOT/build_stock_mentions.py" "$CHAT_MD"
  --html "$STOCK_HTML"
  --json "$STOCK_JSON"
  --markdown "$STOCK_MD"
  --page-history "$HISTORY_JSON"
)
if [[ "$WITH_MARKET_DATA" -eq 1 ]]; then
  final_args+=(--google-finance "$GF_JSON" --stock-trends "$TRENDS_JSON")
  final_args+=(--speaker-dashboard-href "speakers.html")
else
  final_args+=(--no-google-finance)
fi
"$PYTHON_BIN" "${final_args[@]}"
cp "$STOCK_HTML" "$CURRENT_HTML"
cp "$STOCK_HTML" "$CURRENT_INDEX"
cp "$STOCK_HTML" "$DATED_HTML"
if [[ "$WITH_MARKET_DATA" -eq 1 ]]; then
  "$PYTHON_BIN" "$ROOT/build_speaker_stock_dashboard.py" \
    --input-dir "$OUT_DIR" \
    --output "$SPEAKERS_HTML" \
    --json "$SPEAKERS_JSON" \
    --daily-k "$SPEAKER_DAILY_K" \
    --days 15
fi
{
  printf "/stock_mentions.json /%s/stock_mentions.json 302\n" "$RUN_DATE"
  printf "/stock_mentions.md /%s/stock_mentions.md 302\n" "$RUN_DATE"
  if [[ "$WITH_MARKET_DATA" -eq 1 ]]; then
    printf "/google_finance_snapshot.json /%s/google_finance_snapshot.json 302\n" "$RUN_DATE"
    printf "/stock_trends.json /%s/stock_trends.json 302\n" "$RUN_DATE"
  fi
} > "$REDIRECTS_FILE"

echo "==> local output"
echo "    $STOCK_HTML"
echo "    $CURRENT_HTML"
echo "    $CURRENT_INDEX"
echo "    $DATED_HTML"
if [[ "$WITH_MARKET_DATA" -eq 1 ]]; then
  echo "    $SPEAKERS_HTML"
fi
echo "    $REDIRECTS_FILE"

if [[ "$DO_DEPLOY" -eq 0 ]]; then
  echo "==> skip Cloudflare deploy (pass --deploy to publish)"
  exit 0
fi

if [[ -z "$WRANGLER_BIN" ]]; then
  echo "wrangler not found. Install Cloudflare Wrangler or set WRANGLER_BIN." >&2
  exit 1
fi

if [[ "$CREATE_PROJECT" -eq 1 ]]; then
  echo "==> create Cloudflare Pages project if needed: $PROJECT_NAME"
  "$WRANGLER_BIN" pages project create "$PROJECT_NAME" --production-branch "$BRANCH" || true
fi

echo "==> deploy to Cloudflare Pages: $PROJECT_NAME / $BRANCH"
"$WRANGLER_BIN" pages deploy "$OUT_DIR" \
  --project-name "$PROJECT_NAME" \
  --branch "$BRANCH" \
  --commit-dirty=true \
  --commit-message "Daily WeChat stock dashboard $RUN_DATE"
