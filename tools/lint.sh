#!/usr/bin/env sh
set -e  # Exit on first error

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
dirs="teleclaude tools bin"

# Use venv directly if available (avoids uv network calls in CI),
# fall back to uv run for local development.
if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    RUN="${REPO_ROOT}/.venv/bin/python"
    RUN_M="${REPO_ROOT}/.venv/bin/python -m"
    RUFF="${REPO_ROOT}/.venv/bin/ruff"
    PYRIGHT="${REPO_ROOT}/.venv/bin/pyright"
    export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
else
    RUN="uv run --quiet python"
    RUN_M="uv run --quiet -m"
    RUFF="uv run --quiet ruff"
    PYRIGHT="uv run --quiet pyright"
fi

echo "Running lint checks"

echo "Running guardrails"
$RUN "${REPO_ROOT}/tools/lint/guardrails.py" "$@"

echo "Running markdown validation"
$RUN "${REPO_ROOT}/tools/lint/markdown.py"

echo "Running resource validation"
if [ "${CI:-}" = "true" ]; then
    echo "  Skipped (CI: telec sync makes network calls)"
else
    $RUN_M teleclaude.cli.telec sync --warn-only --validate-only --project-root "${REPO_ROOT}"
fi

echo "Running ruff format (check)"
$RUFF format --check $dirs

echo "Running ruff check"
$RUN "${REPO_ROOT}/tools/lint/ruff_safe.py" $dirs

echo "Running pyright"
$PYRIGHT
