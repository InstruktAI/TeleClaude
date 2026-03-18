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
        # Scope to staged Python files for fast pre-commit feedback.
        # Full-codebase pylint runs in CI; pre-commit checks only what changed.
        staged_py=$(git diff --cached --name-only --diff-filter=ACM -- '*.py' | grep '^teleclaude/' || true)
        if [ -z "$staged_py" ]; then
            exit 0
        fi
        # shellcheck disable=SC2086
        $PYLINT $staged_py
        ;;
    parallel-typecheck)
        # Run pyright, mypy, and pylint concurrently. Collects output and
        # exits non-zero if any checker fails.
        tmpdir=$(mktemp -d)
        trap 'rm -rf "$tmpdir"' EXIT

        # Pyright
        (if $PYRIGHT > "$tmpdir/pyright.out" 2>&1; then
            echo 0 > "$tmpdir/pyright.rc"
        else
            echo $? > "$tmpdir/pyright.rc"
        fi) &
        pid_pyright=$!

        # Mypy
        (if $MYPY > "$tmpdir/mypy.out" 2>&1; then
            echo 0 > "$tmpdir/mypy.rc"
        else
            echo $? > "$tmpdir/mypy.rc"
        fi) &
        pid_mypy=$!

        # Pylint (scoped to staged files)
        staged_py=$(git diff --cached --name-only --diff-filter=ACM -- '*.py' | grep '^teleclaude/' || true)
        (if [ -z "$staged_py" ]; then
            echo 0 > "$tmpdir/pylint.rc"
            echo "(no staged teleclaude/ files)" > "$tmpdir/pylint.out"
        else
            # shellcheck disable=SC2086
            if $PYLINT $staged_py > "$tmpdir/pylint.out" 2>&1; then
                echo 0 > "$tmpdir/pylint.rc"
            else
                echo $? > "$tmpdir/pylint.rc"
            fi
        fi) &
        pid_pylint=$!

        wait $pid_pyright $pid_mypy $pid_pylint

        failed=0
        for checker in pyright mypy pylint; do
            rc=$(cat "$tmpdir/$checker.rc" 2>/dev/null || echo 1)
            if [ "$rc" != "0" ]; then
                echo "=== $checker FAILED ==="
                cat "$tmpdir/$checker.out"
                failed=1
            fi
        done
        exit $failed
        ;;
    *)
        echo "Unknown lint component: $component" >&2
        exit 1
        ;;
esac
