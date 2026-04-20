#!/usr/bin/env sh
# Component-scoped lint hook for pre-commit.
# Usage: ./tools/lint/precommit-hook.sh <component> [files...]
#
# Components: guardrails, ruff-check, pyright, mypy, markdown, docs-validate
set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

# Venv detection (matches lint.sh)
if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    RUN="${REPO_ROOT}/.venv/bin/python"
    RUFF="${REPO_ROOT}/.venv/bin/ruff"
    PYRIGHT="${REPO_ROOT}/.venv/bin/pyright"
    MYPY="${REPO_ROOT}/.venv/bin/mypy"
    export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
else
    RUN="uv run --quiet python"
    RUFF="uv run --quiet ruff"
    PYRIGHT="uv run --quiet pyright"
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
        # Pre-commit must validate the staged snapshot only.
        if [ $# -gt 0 ]; then
            $PYRIGHT "$@"
        else
            $PYRIGHT
        fi
        ;;
    markdown)
        $RUN "${REPO_ROOT}/tools/lint/markdown.py"
        ;;
    docs-validate)
        $RUN "${REPO_ROOT}/tools/lint/docs_validate.py" "$@"
        ;;
    mypy)
        # Pre-commit must validate the staged snapshot only.
        if [ $# -gt 0 ]; then
            $MYPY "$@"
        else
            $MYPY
        fi
        ;;
    parallel-typecheck)
        # Run pyright, mypy concurrently. Collects output and
        # exits non-zero if any checker fails.
        tmpdir=$(mktemp -d)
        trap 'rm -rf "$tmpdir"' EXIT

        # Pyright (staged-file scoped when invoked by pre-commit)
        (if [ $# -gt 0 ]; then
            if $PYRIGHT "$@" > "$tmpdir/pyright.out" 2>&1; then
                echo 0 > "$tmpdir/pyright.rc"
            else
                echo $? > "$tmpdir/pyright.rc"
            fi
        else
            if $PYRIGHT > "$tmpdir/pyright.out" 2>&1; then
                echo 0 > "$tmpdir/pyright.rc"
            else
                echo $? > "$tmpdir/pyright.rc"
            fi
        fi) &
        pid_pyright=$!

        # Mypy (staged-file scoped when invoked by pre-commit)
        (if [ $# -gt 0 ]; then
            if $MYPY "$@" > "$tmpdir/mypy.out" 2>&1; then
                echo 0 > "$tmpdir/mypy.rc"
            else
                echo $? > "$tmpdir/mypy.rc"
            fi
        else
            if $MYPY > "$tmpdir/mypy.out" 2>&1; then
                echo 0 > "$tmpdir/mypy.rc"
            else
                echo $? > "$tmpdir/mypy.rc"
            fi
        fi) &
        pid_mypy=$!

        wait $pid_pyright $pid_mypy

        failed=0
        for checker in pyright mypy; do
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
