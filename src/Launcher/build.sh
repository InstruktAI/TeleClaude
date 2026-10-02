#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

exec env "PYTHONPATH=$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" -m teleclaude.install.launcher_identity \
    --intent build \
    --project-root "$REPO_ROOT"
