#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s {e2e|agents|meta}\n' "$0" >&2
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

case "$1" in
    e2e)
        echo "Running integration/e2e tests..."
        uv run pytest tests/integration/ -v -m "not expensive"
        echo "✓ Integration tests passed"
        ;;
    agents)
        echo "Running agent invocation matrix (real LLM calls)..."
        uv run pytest tests/integration/test_agent_invocation_matrix.py -v -m expensive -o "addopts="
        echo "✓ Agent matrix tests passed"
        ;;
    meta)
        echo "Running process meta tests (serial, isolated harness)..."
        uv run pytest tests/process/ -o "addopts=" --timeout=60
        echo "✓ Process meta tests passed"
        ;;
    *)
        usage
        exit 2
        ;;
esac
