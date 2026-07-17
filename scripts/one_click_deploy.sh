#!/usr/bin/env bash
# One-command local build, with market data and optional Cloudflare Pages deployment.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

OUT_DIR="${OUT_DIR:-$ROOT/exports/group_stock_dashboard}"
GROUP_NAME="${WECHAT_GROUP_NAME:-${GROUP_NAME:-}}"
CHAT_MD="${CHAT_MD:-}"
RUN_DATE="${RUN_DATE:-}"
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

DO_DEPLOY=0
CREATE_PROJECT=0
WITH_MARKET_DATA="${WITH_MARKET_DATA:-1}"
MARKET_DATA_CHANNEL="${MARKET_DATA_CHANNEL:-auto}"

usage() {
  cat <<EOF
Usage: $0 [--with-market-data] [--deploy] [--create-project] [--no-market-data]

Input options:
  CHAT_MD=/path/to/chat.md       Use an existing markdown export.
  WECHAT_GROUP_NAME="Group"      Export this group through wechat-cli.

Environment:
  OUT_DIR                        default: ./exports/group_stock_dashboard
  RUN_DATE                       default: first date in CHAT_MD, or today
  WITH_MARKET_DATA               default: 1; set 0 or pass --no-market-data to skip market fetches
  MARKET_DATA_CHANNEL            default: auto; one of auto, google, sina
  CHAT_STOCK_SELF_NAME           optional display name for exported sender "me"
  CF_PAGES_PROJECT_NAME          default: group-stock-dashboard
  CF_PAGES_BRANCH                default: main

Examples:
  CHAT_MD=examples/sample_chat.md $0
  CHAT_MD=examples/sample_chat.md $0 --no-market-data
  WECHAT_GROUP_NAME="My Group" $0
  CHAT_MD=exports/raw/2026-07-17.md $0 --deploy --create-project
EOF
}

for arg in "$@"; do
  case "$arg" in
    --deploy) DO_DEPLOY=1 ;;
    --create-project) CREATE_PROJECT=1 ;;
    --with-market-data) WITH_MARKET_DATA=1 ;;
    --no-market-data) WITH_MARKET_DATA=0 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$CHAT_MD" && ! -s "$CHAT_MD" ]]; then
  echo "CHAT_MD does not exist or is empty: $CHAT_MD" >&2
  exit 1
fi

if [[ -z "$CHAT_MD" && -z "$GROUP_NAME" ]]; then
  echo "Provide either CHAT_MD or WECHAT_GROUP_NAME." >&2
  usage >&2
  exit 2
fi

if [[ -z "$RUN_DATE" && -n "$CHAT_MD" ]]; then
  RUN_DATE="$("$PYTHON_BIN" - "$CHAT_MD" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
match = re.search(r"^- \[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\]", text, flags=re.M)
print(match.group(1) if match else "")
PY
)"
fi
RUN_DATE="${RUN_DATE:-$(date +%F)}"

DATED_DIR="$OUT_DIR/$RUN_DATE"
mkdir -p "$DATED_DIR"

CHAT_OUT="$DATED_DIR/chat.md"
STOCK_HTML="$DATED_DIR/index.html"
STOCK_JSON="$DATED_DIR/stock_mentions.json"
STOCK_MD="$DATED_DIR/stock_mentions.md"
GF_JSON="$DATED_DIR/google_finance_snapshot.json"
TRENDS_JSON="$DATED_DIR/stock_trends.json"
HISTORY_JSON="$OUT_DIR/page_history.json"
SPEAKERS_HTML="$OUT_DIR/speakers.html"
SPEAKERS_JSON="$OUT_DIR/speakers.json"
SPEAKER_DAILY_K="$OUT_DIR/speaker_daily_k.json"

if [[ -n "$CHAT_MD" ]]; then
  cp "$CHAT_MD" "$CHAT_OUT"
else
  echo "==> export WeChat group: $GROUP_NAME / $RUN_DATE"
  "$WECHAT_BIN" export "$GROUP_NAME" \
    --start-time "$RUN_DATE" \
    --end-time "$RUN_DATE" \
    --limit 10000 \
    --format markdown \
    --output "$CHAT_OUT"
fi

echo "==> build stock list"
"$PYTHON_BIN" "$ROOT/build_stock_mentions.py" "$CHAT_OUT" \
  --html "$STOCK_HTML" \
  --json "$STOCK_JSON" \
  --markdown "$STOCK_MD" \
  --no-google-finance

if [[ "$WITH_MARKET_DATA" -eq 1 ]]; then
  echo "==> fetch market snapshot ($MARKET_DATA_CHANNEL)"
  "$PYTHON_BIN" "$ROOT/fetch_google_finance_snapshot.py" "$STOCK_JSON" --output "$GF_JSON" --channel "$MARKET_DATA_CHANNEL"

  echo "==> fetch intraday trends"
  "$PYTHON_BIN" "$ROOT/fetch_stock_trends.py" "$STOCK_JSON" --output "$TRENDS_JSON"
fi

echo "==> update page history"
"$PYTHON_BIN" "$ROOT/update_page_history.py" \
  --history "$HISTORY_JSON" \
  --date "$RUN_DATE" \
  --href "${RUN_DATE}/" \
  --title "${GROUP_NAME:-$(basename "$CHAT_OUT" .md)}" \
  --stock-json "$STOCK_JSON" \
  --version "$RUN_VERSION"

echo "==> build final dashboard"
final_args=(
  "$ROOT/build_stock_mentions.py" "$CHAT_OUT"
  --html "$STOCK_HTML"
  --json "$STOCK_JSON"
  --markdown "$STOCK_MD"
  --page-history "$HISTORY_JSON"
)
final_args+=(--speaker-dashboard-href "speakers.html")
if [[ "$WITH_MARKET_DATA" -eq 1 ]]; then
  final_args+=(--google-finance "$GF_JSON" --stock-trends "$TRENDS_JSON")
else
  final_args+=(--no-google-finance)
fi
"$PYTHON_BIN" "${final_args[@]}"

cp "$STOCK_HTML" "$OUT_DIR/index.html"
cp "$STOCK_HTML" "$OUT_DIR/stock_mentions.html"
cp "$STOCK_HTML" "$OUT_DIR/${RUN_DATE}.html"
{
  printf "/stock_mentions.json /%s/stock_mentions.json 302\n" "$RUN_DATE"
  printf "/stock_mentions.md /%s/stock_mentions.md 302\n" "$RUN_DATE"
  if [[ "$WITH_MARKET_DATA" -eq 1 ]]; then
    printf "/google_finance_snapshot.json /%s/google_finance_snapshot.json 302\n" "$RUN_DATE"
    printf "/stock_trends.json /%s/stock_trends.json 302\n" "$RUN_DATE"
  fi
} > "$OUT_DIR/_redirects"

echo "==> build speaker dashboard"
speaker_args=(
  "$ROOT/build_speaker_stock_dashboard.py"
  --input-dir "$OUT_DIR"
  --output "$SPEAKERS_HTML"
  --json "$SPEAKERS_JSON"
  --daily-k "$SPEAKER_DAILY_K"
  --days 15
)
if [[ "$WITH_MARKET_DATA" -ne 1 ]]; then
  speaker_args+=(--no-daily-k)
fi
"$PYTHON_BIN" "${speaker_args[@]}"

echo "==> output: $OUT_DIR/index.html"

if [[ "$DO_DEPLOY" -eq 0 ]]; then
  echo "==> skip Cloudflare deploy (pass --deploy to publish)"
  exit 0
fi

if [[ -z "$WRANGLER_BIN" ]]; then
  echo "wrangler not found. Install Cloudflare Wrangler or set WRANGLER_BIN." >&2
  exit 1
fi

if [[ "$CREATE_PROJECT" -eq 1 ]]; then
  "$WRANGLER_BIN" pages project create "$PROJECT_NAME" --production-branch "$BRANCH" || true
fi

"$WRANGLER_BIN" pages deploy "$OUT_DIR" \
  --project-name "$PROJECT_NAME" \
  --branch "$BRANCH" \
  --commit-dirty=true \
  --commit-message "Publish group stock dashboard $RUN_DATE"
