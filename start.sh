#!/usr/bin/env bash
# Friendly root entrypoint for first-time local use.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/scripts/install_and_start.sh" "$@"
