#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "Starting daemon in foreground (Ctrl+C to stop)..."
# shellcheck disable=SC1091
. .venv/bin/activate
python -m teleclaude.daemon
