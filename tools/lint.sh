#!/usr/bin/env sh
set -e  # Exit on first error

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
dirs="teleclaude tools bin tests"

# Use venv directly if available (avoids uv network calls in CI),
# fall back to uv run for local development.
if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    RUN="${REPO_ROOT}/.venv/bin/python"
    RUN_M="${REPO_ROOT}/.venv/bin/python -m"
    RUFF="${REPO_ROOT}/.venv/bin/ruff"
    PYRIGHT="${REPO_ROOT}/.venv/bin/pyright"
    PYLINT="${REPO_ROOT}/.venv/bin/pylint"
    MYPY="${REPO_ROOT}/.venv/bin/mypy"
    export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
else
    RUN="uv run --quiet python"
    RUN_M="uv run --quiet -m"
    RUFF="uv run --quiet ruff"
    PYRIGHT="uv run --quiet pyright"
    PYLINT="uv run --quiet pylint"
    MYPY="uv run --quiet mypy"
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

echo "Running ruff check (auto-fix: imports + lint rules)"
$RUN "${REPO_ROOT}/tools/lint/ruff_safe.py" --fix $dirs

echo "Running ruff format (auto-fix: style)"
$RUFF format $dirs

echo "Running pyright"
$PYRIGHT

echo "Running mypy"
$MYPY

echo "Running pylint"
# pylint 4.x returns non-zero for convention/refactor findings even with --fail-under.
# We use --exit-zero and check the score ourselves.
pylint_output=$($PYLINT teleclaude --exit-zero 2>&1)
pylint_score=$(echo "$pylint_output" | grep "rated at" | grep -o '[0-9]*\.[0-9]*' | head -1)
echo "$pylint_output" | tail -3
if [ -n "$pylint_score" ]; then
    required="9.00"
    if [ "$(echo "$pylint_score < $required" | bc -l)" = "1" ]; then
        echo "pylint score $pylint_score is below minimum $required"
        exit 1
    fi
fi
