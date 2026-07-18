#!/usr/bin/env bash
# Stage only public dashboard artifacts before deploying to Cloudflare Pages.

set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 OUT_DIR PROJECT_NAME BRANCH COMMIT_MESSAGE" >&2
  exit 2
fi

SOURCE_DIR="$1"
PROJECT_NAME="$2"
BRANCH="$3"
COMMIT_MESSAGE="$4"
WRANGLER_BIN="${WRANGLER_BIN:-wrangler}"

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "dashboard output directory does not exist: $SOURCE_DIR" >&2
  exit 1
fi

STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/group-stock-pages.XXXXXX")"
cleanup() {
  rm -rf -- "$STAGING_DIR"
}
trap cleanup EXIT

cp -R "$SOURCE_DIR/." "$STAGING_DIR/"
find "$STAGING_DIR" -type f \( \
  -name 'chat.md' -o \
  -name 'codex_analysis.json' -o \
  -name 'codex_raw_analysis.json' \
\) -delete

if find "$STAGING_DIR" -type f \( -name 'chat.md' -o -name 'codex_*analysis.json' \) | grep -q .; then
  echo "privacy check failed: private analysis source remains in deployment staging" >&2
  exit 1
fi

"$WRANGLER_BIN" pages deploy "$STAGING_DIR" \
  --project-name "$PROJECT_NAME" \
  --branch "$BRANCH" \
  --commit-dirty=true \
  --commit-message "$COMMIT_MESSAGE"
