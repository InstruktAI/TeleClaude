#!/usr/bin/env sh
set -eu

# Thin wrapper — delegates to telec repo test via the project venv.
# Kept for backward compatibility with Makefile and CI.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    exec "${REPO_ROOT}/.venv/bin/python" -m teleclaude.cli.telec repo test "$@"
else
    exec telec repo test "$@"
fi
