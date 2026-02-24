#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_ACTIVATE="${REPO_ROOT}/.venv/bin/activate"

if [ ! -f "${VENV_ACTIVATE}" ]; then
  echo "ERROR: missing virtualenv activation script: ${VENV_ACTIVATE}" >&2
  echo "Run 'uv sync --extra test' from ${REPO_ROOT} first." >&2
  exit 2
fi

cd "${REPO_ROOT}"
. "${VENV_ACTIVATE}"

# Force tests to use sandboxed config and env files
export TELECLAUDE_CONFIG_PATH="${TELECLAUDE_CONFIG_PATH:-tests/integration/config.yml}"
export TELECLAUDE_ENV_PATH="${TELECLAUDE_ENV_PATH:-tests/integration/.env}"

# Run unit and integration suites separately with strict per-test timeouts.
# Expensive tests (real LLM API calls) are excluded by default — use `make test-agents`.
TEST_TIMEOUT="${TELECLAUDE_TEST_TIMEOUT:-20m}"
if [ "${1:-}" = "--cov" ]; then
    echo "Running tests with coverage..."
    timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -n auto -m "not expensive" --cov=teleclaude --cov-report=html --cov-report=term-missing

    # Generate absolute path for clickable link
    REPORT_PATH="$(pwd)/coverage/html/index.html"
    echo ""
    echo "✓ Coverage report generated: file://$REPORT_PATH"
else
    timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -n auto -m "not expensive" -q
fi
