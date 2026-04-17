#!/usr/bin/env sh
set -e

# Thin wrapper — delegates to telec code lint via the project venv.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

for _lint_arg in "$@"; do
    case "$_lint_arg" in
        --dry-run) echo "Running lint checks"; exit 0 ;;
    esac
done

if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    exec "${REPO_ROOT}/.venv/bin/python" -m teleclaude.cli.telec code lint "$@"
else
    exec telec code lint "$@"
fi
