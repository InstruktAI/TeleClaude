#!/usr/bin/env sh
# Component-scoped lint hook for pre-commit.
# Usage: ./tools/lint/precommit-hook.sh <component> [files...]
#
# Components: guardrails, ruff-check, pyright, mypy, pylint, markdown
set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

# Venv detection (matches lint.sh)
if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    RUN="${REPO_ROOT}/.venv/bin/python"
    RUFF="${REPO_ROOT}/.venv/bin/ruff"
    PYRIGHT="${REPO_ROOT}/.venv/bin/pyright"
    PYLINT="${REPO_ROOT}/.venv/bin/pylint"
    MYPY="${REPO_ROOT}/.venv/bin/mypy"
    export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
else
    RUN="uv run --quiet python"
    RUFF="uv run --quiet ruff"
    PYRIGHT="uv run --quiet pyright"
    PYLINT="uv run --quiet pylint"
    MYPY="uv run --quiet mypy"
fi

component="$1"; shift

case "$component" in
    guardrails)
        $RUN "${REPO_ROOT}/tools/lint/guardrails.py" "$@"
        ;;
    ruff-check)
        # Staged Python files from pre-commit; validate only (format hook handles fixes)
        if [ $# -gt 0 ]; then
            $RUFF check "$@"
        else
            $RUFF check teleclaude tools bin
        fi
        ;;
    pyright)
        $PYRIGHT
        ;;
    markdown)
        $RUN "${REPO_ROOT}/tools/lint/markdown.py"
        ;;
    mypy)
        $MYPY
        ;;
    pylint)
        # Match lint.sh: --exit-zero + score threshold (pylint 4.x returns non-zero
        # for convention/refactor findings even with --fail-under)
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
        ;;
    *)
        echo "Unknown lint component: $component" >&2
        exit 1
        ;;
esac
