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

# Parse flags
DRY_RUN=""
for _lint_arg in "$@"; do
    case "$_lint_arg" in
        --dry-run) DRY_RUN=1 ;;
    esac
done

echo "Running lint checks"

# Global checks: guardrails, markdown, and resource validation run unconditionally —
# they are fast, project-global, and excluded from session-scope narrowing.
echo "Running guardrails"
if [ -z "$DRY_RUN" ]; then
    $RUN "${REPO_ROOT}/tools/lint/guardrails.py"

    echo "Running markdown validation"
    $RUN "${REPO_ROOT}/tools/lint/markdown.py"

    echo "Running resource validation"
    if [ "${CI:-}" = "true" ]; then
        echo "  Skipped (CI: telec sync makes network calls)"
    else
        $RUN_M teleclaude.cli.telec sync --warn-only --validate-only --project-root "${REPO_ROOT}"
    fi
fi

# Session scope detection: attempt to resolve files touched by the current agent session.
# Exit 2 → no session (normal non-agent context, fall back silently).
# Exit 3 → session detected but collection failed (emit diagnostic on stderr, fall back).
SCOPED_FILES=""
_scope_stderr_tmp=$(mktemp)
if _scope_out=$($RUN "${REPO_ROOT}/tools/session_scope.py" --mode lint 2>"$_scope_stderr_tmp"); then
    SCOPED_FILES="$_scope_out"
    if [ -n "$SCOPED_FILES" ]; then
        _file_count=$(echo "$SCOPED_FILES" | wc -l | tr -d ' ')
        echo "Session-scoped lint: ${_file_count} files"
    fi
else
    _scope_exit=$?
    if [ "$_scope_exit" -eq 3 ]; then
        cat "$_scope_stderr_tmp" >&2
    fi
fi
rm -f "$_scope_stderr_tmp"

[ -n "$DRY_RUN" ] && exit 0

echo "Running ruff check (auto-fix: imports + lint rules)"
if [ -n "$SCOPED_FILES" ]; then
    # shellcheck disable=SC2086
    $RUN "${REPO_ROOT}/tools/lint/ruff_safe.py" --fix $SCOPED_FILES
else
    $RUN "${REPO_ROOT}/tools/lint/ruff_safe.py" --fix $dirs
fi

echo "Running ruff format (auto-fix: style)"
if [ -n "$SCOPED_FILES" ]; then
    # shellcheck disable=SC2086
    $RUFF format $SCOPED_FILES
else
    $RUFF format $dirs
fi

echo "Running pyright"
if [ -n "$SCOPED_FILES" ]; then
    # shellcheck disable=SC2086
    $PYRIGHT $SCOPED_FILES
else
    $PYRIGHT
fi

echo "Running mypy"
if [ -n "$SCOPED_FILES" ]; then
    # shellcheck disable=SC2086
    $MYPY $SCOPED_FILES
else
    $MYPY
fi

echo "Running pylint"
if [ -n "$SCOPED_FILES" ]; then
    # shellcheck disable=SC2086
    $PYLINT $SCOPED_FILES
else
    $PYLINT teleclaude
fi
