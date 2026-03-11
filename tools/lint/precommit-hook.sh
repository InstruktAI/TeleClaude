#!/usr/bin/env sh
# Component-scoped lint hook for pre-commit.
# Usage: ./tools/lint/precommit-hook.sh <component> [files...]
#
# Components: guardrails, ruff-check, pyright, markdown, pylint
set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

# Venv detection (matches lint.sh)
if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    RUN="${REPO_ROOT}/.venv/bin/python"
    RUFF="${REPO_ROOT}/.venv/bin/ruff"
    PYRIGHT="${REPO_ROOT}/.venv/bin/pyright"
    PYLINT="${REPO_ROOT}/.venv/bin/pylint"
    export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
else
    RUN="uv run --quiet python"
    RUFF="uv run --quiet ruff"
    PYRIGHT="uv run --quiet pyright"
    PYLINT="uv run --quiet pylint"
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
    pylint)
        $PYLINT --exit-zero teleclaude
        ;;
    *)
        echo "Unknown lint component: $component" >&2
        exit 1
        ;;
esac
