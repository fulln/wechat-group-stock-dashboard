#!/usr/bin/env bash
# Install local runtime bits and generate/open the static dashboard.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

CHAT_MD="${CHAT_MD:-}"
GROUP_NAME="${WECHAT_GROUP_NAME:-${GROUP_NAME:-}}"
SELF_NAME="${CHAT_STOCK_SELF_NAME:-}"
MARKET_DATA_CHANNEL="${MARKET_DATA_CHANNEL:-auto}"
WITH_MARKET_DATA="${WITH_MARKET_DATA:-1}"
DO_DEPLOY=0
CREATE_PROJECT=0
OPEN_PAGE=1
INSTALL_SKILL=0
INSTALL_WECHAT_CLI="${INSTALL_WECHAT_CLI:-0}"
SETUP_ONLY=0
OUT_DIR="${OUT_DIR:-$ROOT/exports/group_stock_dashboard}"
TOOLS_DIR="${TOOLS_DIR:-$ROOT/.tools}"
WECHAT_CLI_PACKAGE="${WECHAT_CLI_PACKAGE:-@canghe_ai/wechat-cli}"

usage() {
  cat <<EOF
Usage: ./start.sh [options]

Options:
  --chat-md PATH             Use an existing markdown chat export.
  --group-name NAME          Export this WeChat group through wechat-cli.
  --self-name NAME           Display exported sender "me" as NAME.
  --market-channel NAME      auto, google, or sina. Default: auto.
  --no-market-data           Skip external market fetches.
  --with-market-data         Enable external market fetches. Default.
  --deploy                   Deploy generated static files to Cloudflare Pages.
  --create-project           Create Cloudflare Pages project before deploy.
  --install-wechat-cli       Install wechat-cli locally under .tools/.
  --install-skill            Install bundled Codex skill to ~/.codex/skills.
  --setup-only               Install/configure tools, then exit before building.
  --no-open                  Do not open the generated HTML locally.
  -h, --help                 Show this help.

Defaults:
  If neither --chat-md nor --group-name is provided, the sample chat is used.
  Generated page: exports/group_stock_dashboard/index.html
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --chat-md)
      CHAT_MD="$2"
      shift 2
      ;;
    --group-name)
      GROUP_NAME="$2"
      shift 2
      ;;
    --self-name)
      SELF_NAME="$2"
      shift 2
      ;;
    --market-channel)
      MARKET_DATA_CHANNEL="$2"
      shift 2
      ;;
    --no-market-data)
      WITH_MARKET_DATA=0
      shift
      ;;
    --with-market-data)
      WITH_MARKET_DATA=1
      shift
      ;;
    --deploy)
      DO_DEPLOY=1
      shift
      ;;
    --create-project)
      CREATE_PROJECT=1
      shift
      ;;
    --install-wechat-cli)
      INSTALL_WECHAT_CLI=1
      shift
      ;;
    --install-skill)
      INSTALL_SKILL=1
      shift
      ;;
    --setup-only)
      SETUP_ONLY=1
      shift
      ;;
    --no-open)
      OPEN_PAGE=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$MARKET_DATA_CHANNEL" in
  auto|google|sina) ;;
  *)
    echo "--market-channel must be one of: auto, google, sina" >&2
    exit 2
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.10+ first." >&2
  exit 1
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "==> create virtualenv: .venv"
  python3 -m venv "$ROOT/.venv"
fi

PYTHON_BIN="$ROOT/.venv/bin/python"
echo "==> install local package"
"$PYTHON_BIN" -m pip install --upgrade pip >/dev/null
"$PYTHON_BIN" -m pip install -e "$ROOT" >/dev/null

if [[ ! -f "$ROOT/.env" ]]; then
  echo "==> create .env from .env.example"
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

ensure_wechat_cli() {
  local requested_bin="${WECHAT_BIN:-wechat-cli}"
  if command -v "$requested_bin" >/dev/null 2>&1; then
    WECHAT_BIN="$(command -v "$requested_bin")"
    export WECHAT_BIN
    echo "==> found wechat-cli: $WECHAT_BIN"
    return 0
  fi

  local local_bin="$TOOLS_DIR/node_modules/.bin/wechat-cli"
  if [[ -x "$local_bin" ]]; then
    WECHAT_BIN="$local_bin"
    export WECHAT_BIN
    echo "==> found local wechat-cli: $WECHAT_BIN"
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required to install wechat-cli. Install Node.js/npm, or set WECHAT_BIN to an existing wechat-cli path." >&2
    exit 1
  fi

  echo "==> install wechat-cli locally: $WECHAT_CLI_PACKAGE"
  mkdir -p "$TOOLS_DIR"
  npm --prefix "$TOOLS_DIR" install "$WECHAT_CLI_PACKAGE" >/dev/null

  if [[ ! -x "$local_bin" ]]; then
    echo "wechat-cli install finished, but command was not found at: $local_bin" >&2
    exit 1
  fi
  WECHAT_BIN="$local_bin"
  export WECHAT_BIN
}

if [[ "$INSTALL_SKILL" -eq 1 ]]; then
  echo "==> install Codex skill"
  mkdir -p "$HOME/.codex/skills"
  rm -rf "$HOME/.codex/skills/wechat-group-stock-dashboard"
  cp -R "$ROOT/codex-skill/wechat-group-stock-dashboard" "$HOME/.codex/skills/"
fi

if [[ "$INSTALL_WECHAT_CLI" -eq 1 || -n "$GROUP_NAME" ]]; then
  ensure_wechat_cli
fi

if [[ "$SETUP_ONLY" -eq 1 ]]; then
  echo "==> setup complete"
  exit 0
fi

if [[ -z "$CHAT_MD" && -z "$GROUP_NAME" ]]; then
  CHAT_MD="$ROOT/examples/sample_chat.md"
  echo "==> no input provided, use sample chat: $CHAT_MD"
fi

if [[ -n "$CHAT_MD" && ! -s "$CHAT_MD" ]]; then
  echo "chat markdown does not exist or is empty: $CHAT_MD" >&2
  exit 1
fi

if [[ -n "$GROUP_NAME" ]] && ! command -v "${WECHAT_BIN:-wechat-cli}" >/dev/null 2>&1; then
  echo "wechat-cli not found, but --group-name was provided. Use --install-wechat-cli or --chat-md." >&2
  exit 1
fi

if [[ "$DO_DEPLOY" -eq 1 ]] && ! command -v "${WRANGLER_BIN:-wrangler}" >/dev/null 2>&1; then
  echo "wrangler not found, but --deploy was provided. Install Wrangler and run wrangler login first." >&2
  exit 1
fi

args=()
if [[ "$DO_DEPLOY" -eq 1 ]]; then
  args+=(--deploy)
fi
if [[ "$CREATE_PROJECT" -eq 1 ]]; then
  args+=(--create-project)
fi
if [[ "$WITH_MARKET_DATA" -eq 0 ]]; then
  args+=(--no-market-data)
else
  args+=(--with-market-data)
fi

echo "==> build dashboard"
CHAT_MD="$CHAT_MD" \
WECHAT_GROUP_NAME="$GROUP_NAME" \
CHAT_STOCK_SELF_NAME="$SELF_NAME" \
MARKET_DATA_CHANNEL="$MARKET_DATA_CHANNEL" \
WITH_MARKET_DATA="$WITH_MARKET_DATA" \
OUT_DIR="$OUT_DIR" \
PYTHON_BIN="$PYTHON_BIN" \
WECHAT_BIN="${WECHAT_BIN:-wechat-cli}" \
"$ROOT/scripts/one_click_deploy.sh" "${args[@]}"

index_html="$OUT_DIR/index.html"
speakers_html="$OUT_DIR/speakers.html"
echo "==> dashboard ready"
echo "    $index_html"
if [[ -f "$speakers_html" ]]; then
  echo "    $speakers_html"
fi

if [[ "$OPEN_PAGE" -eq 1 ]]; then
  if command -v open >/dev/null 2>&1; then
    echo "==> open local HTML"
    open "$index_html"
  else
    echo "==> open this file in your browser: $index_html"
  fi
fi
