#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Test suite is being rebuilt from scratch after the large-file refactor.
# See todos/test-suite-overhaul/ and todos/refactor-large-files/.
if [ ! -d "tests/unit" ] || [ -z "$(ls tests/unit/*.py 2>/dev/null || true)" ]; then
    echo "⏸ Test suite pending rebuild — skipping."
    exit 0
fi

VENV_ACTIVATE="${REPO_ROOT}/.venv/bin/activate"

if [ ! -f "${VENV_ACTIVATE}" ]; then
  echo "ERROR: missing virtualenv activation script: ${VENV_ACTIVATE}" >&2
  echo "Run 'uv sync --extra test' from ${REPO_ROOT} first." >&2
  exit 2
fi

. "${VENV_ACTIVATE}"

# Force tests to use sandboxed config and env files
export TELECLAUDE_CONFIG_PATH="${TELECLAUDE_CONFIG_PATH:-tests/integration/config.yml}"
export TELECLAUDE_ENV_PATH="${TELECLAUDE_ENV_PATH:-tests/integration/.env}"

# Run unit and integration suites separately with strict per-test timeouts.
# Expensive tests (real LLM API calls) are excluded by default — use `make test-agents`.
TEST_TIMEOUT="${TELECLAUDE_TEST_TIMEOUT:-20m}"

# Session scope detection: map session-touched source files to their test companions.
# Exit 2 → no session (normal non-agent context, fall back silently).
# Exit 3 → session detected but collection failed (emit diagnostic on stderr, fall back).
SCOPED_TEST_FILES=""
_scope_stderr_tmp=$(mktemp)
if _scope_out=$("${REPO_ROOT}/.venv/bin/python" "${REPO_ROOT}/tools/session_scope.py" --mode test 2>"$_scope_stderr_tmp"); then
    SCOPED_TEST_FILES="$_scope_out"
    if [ -n "$SCOPED_TEST_FILES" ]; then
        _file_count=$(echo "$SCOPED_TEST_FILES" | wc -l | tr -d ' ')
        echo "Session-scoped test: ${_file_count} test files"
    fi
else
    _scope_exit=$?
    if [ "$_scope_exit" -eq 3 ]; then
        cat "$_scope_stderr_tmp" >&2
    fi
fi
rm -f "$_scope_stderr_tmp"

if [ "${1:-}" = "--cov" ]; then
    echo "Running tests with coverage..."
    if [ -n "$SCOPED_TEST_FILES" ]; then
        # shellcheck disable=SC2086
        timeout "${TEST_TIMEOUT}" pytest $SCOPED_TEST_FILES -m "not expensive" --cov=teleclaude --cov-report=html --cov-report=term-missing
    else
        timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -m "not expensive" --cov=teleclaude --cov-report=html --cov-report=term-missing
    fi

    # Generate absolute path for clickable link
    REPORT_PATH="$(pwd)/coverage/html/index.html"
    echo ""
    echo "✓ Coverage report generated: file://$REPORT_PATH"
else
    if [ -n "$SCOPED_TEST_FILES" ]; then
        # shellcheck disable=SC2086
        timeout "${TEST_TIMEOUT}" pytest $SCOPED_TEST_FILES -m "not expensive" -q
    else
        timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -m "not expensive" -q
    fi
fi
