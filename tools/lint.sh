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

[ -n "$DRY_RUN" ] && exit 0

# Worktree detection: scope lint to session-touched files when inside a worktree.
# Outside a worktree, run repo-wide.
_GIT_COMMON=$(git -C "${REPO_ROOT}" rev-parse --git-common-dir 2>/dev/null || true)
_GIT_DIR=$(git -C "${REPO_ROOT}" rev-parse --git-dir 2>/dev/null || true)
SCOPED_FILES=""
IN_WORKTREE=""
if [ -n "$_GIT_COMMON" ] && [ -n "$_GIT_DIR" ] && [ "$_GIT_COMMON" != "$_GIT_DIR" ]; then
    IN_WORKTREE=1
    _scope_stderr_tmp=$(mktemp)
    if _scope_out=$($RUN "${REPO_ROOT}/tools/session_scope.py" --mode lint --project-root "${REPO_ROOT}" 2>"$_scope_stderr_tmp"); then
        SCOPED_FILES="$_scope_out"
        if [ -n "$SCOPED_FILES" ]; then
            _file_count=$(echo "$SCOPED_FILES" | wc -l | tr -d ' ')
            echo "Worktree-scoped lint: ${_file_count} files"
        else
            echo "Worktree-scoped lint: no Python files touched — skipping"
            rm -f "$_scope_stderr_tmp"
            exit 0
        fi
    else
        _scope_exit=$?
        echo "ERROR: worktree lint scope resolution failed (exit $_scope_exit)" >&2
        cat "$_scope_stderr_tmp" >&2
        rm -f "$_scope_stderr_tmp"
        exit 1
    fi
    rm -f "$_scope_stderr_tmp"
fi

echo "Running guardrails"
if [ -n "$SCOPED_FILES" ]; then
    # shellcheck disable=SC2086
    $RUN "${REPO_ROOT}/tools/lint/guardrails.py" $SCOPED_FILES
else
    $RUN "${REPO_ROOT}/tools/lint/guardrails.py"
fi

echo "Running markdown validation"
$RUN "${REPO_ROOT}/tools/lint/markdown.py"

echo "Running resource validation"
if [ "${CI:-}" = "true" ]; then
    echo "  Skipped (CI: telec sync makes network calls)"
else
    $RUN_M teleclaude.cli.telec sync --warn-only --validate-only --project-root "${REPO_ROOT}"
fi

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
