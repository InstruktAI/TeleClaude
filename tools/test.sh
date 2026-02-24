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
# Fixed worker count is faster and less variable than -n auto under strict 10s gate.
# Local stress runs show 10 workers with default distribution gives best tail latency.
PYTEST_WORKERS="${TELECLAUDE_PYTEST_WORKERS:-10}"
TEST_TIMEOUT="${TELECLAUDE_TEST_TIMEOUT:-10}"
PYTEST_DIST_MODE="${TELECLAUDE_PYTEST_DIST_MODE:-default}"

# Run unit and integration suites separately with strict per-test timeouts.
# Expensive tests (real LLM API calls) are excluded by default — use `make test-agents`.
if [ "${1:-}" = "--cov" ]; then
    echo "Running tests with coverage..."
    if [ "${PYTEST_DIST_MODE}" = "default" ]; then
        timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -n "${PYTEST_WORKERS}" -m "not expensive" --cov=teleclaude --cov-report=html --cov-report=term-missing
    else
        timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -n "${PYTEST_WORKERS}" --dist "${PYTEST_DIST_MODE}" -m "not expensive" --cov=teleclaude --cov-report=html --cov-report=term-missing
    fi

    # Generate absolute path for clickable link
    REPORT_PATH="$(pwd)/coverage/html/index.html"
    echo ""
    echo "✓ Coverage report generated: file://$REPORT_PATH"
else
    if [ "${PYTEST_DIST_MODE}" = "default" ]; then
        timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -n "${PYTEST_WORKERS}" -m "not expensive" -q --disable-warnings
    else
        timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -n "${PYTEST_WORKERS}" --dist "${PYTEST_DIST_MODE}" -m "not expensive" -q --disable-warnings
    fi
fi
