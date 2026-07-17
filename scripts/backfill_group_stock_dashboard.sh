#!/usr/bin/env bash
# Backfill multiple daily dashboards at a gentle cadence.

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

PROJECT_NAME="${CF_PAGES_PROJECT_NAME:-group-stock-dashboard}"
BRANCH="${CF_PAGES_BRANCH:-main}"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi
WRANGLER_BIN="${WRANGLER_BIN:-$(command -v wrangler || true)}"
DAILY_SCRIPT="$ROOT/scripts/daily_group_stock_dashboard.sh"

END_DATE="$(date +%F)"
DAYS=15
SLEEP_SECONDS=600
DO_DEPLOY=0
FORCE=0
DRY_RUN=0

usage() {
  cat <<EOF
Usage: $0 [--deploy] [--force] [--dry-run] [--days N] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--sleep-seconds N]

Defaults:
  --days 15
  --end-date today
  --sleep-seconds 600

The script runs one date at a time from old to new. Complete date folders are
skipped unless --force is provided.
EOF
}

START_DATE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --deploy) DO_DEPLOY=1; shift ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --days) DAYS="$2"; shift 2 ;;
    --start-date) START_DATE="$2"; shift 2 ;;
    --end-date) END_DATE="$2"; shift 2 ;;
    --sleep-seconds) SLEEP_SECONDS="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$START_DATE" ]]; then
  START_DATE="$("$PYTHON_BIN" - "$END_DATE" "$DAYS" <<'PY'
from datetime import date, timedelta
import sys

end = date.fromisoformat(sys.argv[1])
days = int(sys.argv[2])
if days < 1:
    raise SystemExit("--days must be >= 1")
print((end - timedelta(days=days - 1)).isoformat())
PY
)"
fi

DATES=()
while IFS= read -r day; do
  DATES+=("$day")
done < <("$PYTHON_BIN" - "$START_DATE" "$END_DATE" <<'PY'
from datetime import date, timedelta
import sys

start = date.fromisoformat(sys.argv[1])
end = date.fromisoformat(sys.argv[2])
if start > end:
    raise SystemExit("--start-date must be <= --end-date")
day = start
while day <= end:
    print(day.isoformat())
    day += timedelta(days=1)
PY
)

is_complete_date() {
  local day="$1"
  local dir="$OUT_DIR/$day"
  [[ -s "$dir/chat.md" ]] &&
    [[ -s "$dir/stock_mentions.json" ]] &&
    [[ -s "$dir/google_finance_snapshot.json" ]] &&
    [[ -s "$dir/stock_trends.json" ]] &&
    [[ -s "$dir/index.html" ]]
}

should_run_date() {
  local day="$1"
  [[ "$FORCE" -eq 1 ]] || ! is_complete_date "$day"
}

has_later_runnable_date() {
  local current_idx="$1"
  local idx
  for ((idx = current_idx + 1; idx < ${#DATES[@]}; idx++)); do
    if should_run_date "${DATES[$idx]}"; then
      return 0
    fi
  done
  return 1
}

write_legacy_redirects() {
  local day="$1"
  {
    printf "/stock_mentions.json /%s/stock_mentions.json 302\n" "$day"
    printf "/stock_mentions.md /%s/stock_mentions.md 302\n" "$day"
    printf "/google_finance_snapshot.json /%s/google_finance_snapshot.json 302\n" "$day"
    printf "/stock_trends.json /%s/stock_trends.json 302\n" "$day"
  } > "$OUT_DIR/_redirects"
}

refresh_current_entry() {
  local idx day
  for ((idx = ${#DATES[@]} - 1; idx >= 0; idx--)); do
    day="${DATES[$idx]}"
    if is_complete_date "$day"; then
      "$PYTHON_BIN" "$ROOT/build_stock_mentions.py" "$OUT_DIR/$day/chat.md" \
        --html "$OUT_DIR/$day/index.html" \
        --json "$OUT_DIR/$day/stock_mentions.json" \
        --markdown "$OUT_DIR/$day/stock_mentions.md" \
        --google-finance "$OUT_DIR/$day/google_finance_snapshot.json" \
        --page-history "$OUT_DIR/page_history.json" \
        --stock-trends "$OUT_DIR/$day/stock_trends.json"
      cp "$OUT_DIR/$day/index.html" "$OUT_DIR/stock_mentions.html"
      cp "$OUT_DIR/$day/index.html" "$OUT_DIR/index.html"
      cp "$OUT_DIR/$day/index.html" "$OUT_DIR/${day}.html"
      write_legacy_redirects "$day"
      echo "==> current entry refreshed from: $day"
      return 0
    fi
  done
  echo "!! no complete date found to refresh current entry" >&2
  return 1
}

refresh_speaker_dashboard() {
  "$PYTHON_BIN" "$ROOT/build_speaker_stock_dashboard.py" \
    --input-dir "$OUT_DIR" \
    --output "$OUT_DIR/speakers.html" \
    --json "$OUT_DIR/speakers.json" \
    --daily-k "$OUT_DIR/speaker_daily_k.json" \
    --days 15
}

echo "==> backfill range: $START_DATE -> $END_DATE (${#DATES[@]} days)"
echo "==> sleep between days: ${SLEEP_SECONDS}s"
echo "==> deploy at end: $DO_DEPLOY"
echo "==> force refresh: $FORCE"

if [[ "$DRY_RUN" -eq 1 ]]; then
  for day in "${DATES[@]}"; do
    if ! should_run_date "$day"; then
      echo "SKIP $day (complete)"
    else
      echo "RUN  $day"
    fi
  done
  exit 0
fi

FAILED=()
for idx in "${!DATES[@]}"; do
  day="${DATES[$idx]}"
  ran_date=0
  if ! should_run_date "$day"; then
    echo "==> skip complete date: $day"
  else
    echo "==> run date: $day"
    ran_date=1
    if RUN_DATE="$day" RUN_VERSION="${RUN_VERSION:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}" "$DAILY_SCRIPT"; then
      echo "==> done date: $day"
    else
      echo "!! failed date: $day" >&2
      FAILED+=("$day")
    fi
  fi

  if [[ "$ran_date" -eq 1 ]] && has_later_runnable_date "$idx"; then
    echo "==> sleep ${SLEEP_SECONDS}s before next date"
    sleep "$SLEEP_SECONDS"
  fi
done

refresh_current_entry
refresh_speaker_dashboard

if [[ "$DO_DEPLOY" -eq 1 ]]; then
  if [[ -z "$WRANGLER_BIN" ]]; then
    echo "wrangler not found. Install Cloudflare Wrangler or set WRANGLER_BIN." >&2
    exit 1
  fi
  echo "==> deploy to Cloudflare Pages: $PROJECT_NAME / $BRANCH"
  "$WRANGLER_BIN" pages deploy "$OUT_DIR" \
    --project-name "$PROJECT_NAME" \
    --branch "$BRANCH" \
    --commit-dirty=true \
    --commit-message "Backfill WeChat stock dashboard $START_DATE to $END_DATE"
fi

if [[ "${#FAILED[@]}" -gt 0 ]]; then
  echo "!! failed dates: ${FAILED[*]}" >&2
  exit 1
fi

echo "==> backfill complete"
