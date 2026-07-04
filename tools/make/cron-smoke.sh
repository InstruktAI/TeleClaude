#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

CRON_SMOKE_SINCE="${CRON_SMOKE_SINCE:-15m}"

echo "Listing configured cron jobs..."
uv run python scripts/cron_runner.py --list
echo ""
echo "Recent cron runner failures (last ${CRON_SMOKE_SINCE})..."
instrukt-ai-logs teleclaude --since "$CRON_SMOKE_SINCE" --grep "failed to load job"
