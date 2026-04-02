#!/usr/bin/env sh
set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

if [ -f "${REPO_ROOT}/.venv/bin/pylint" ]; then
    exec "${REPO_ROOT}/.venv/bin/pylint" --disable=all --enable=import-outside-toplevel "$@"
fi

exec uv run --quiet pylint --disable=all --enable=import-outside-toplevel "$@"
