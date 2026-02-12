#!/usr/bin/env sh
set -e  # Exit on first error

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
dirs="teleclaude tools bin"

echo "Running lint checks"

echo "Running guardrails"
uv run --quiet python "${REPO_ROOT}/tools/lint/guardrails.py" "$@"

echo "Running markdown validation"
uv run --quiet "${REPO_ROOT}/tools/lint/markdown.py"

echo "Running resource validation"
uv run --quiet -m teleclaude.cli.telec sync --validate-only --project-root "${REPO_ROOT}"

echo "Running ruff format (check)"
uv run --quiet ruff format --check $dirs

echo "Running ruff check"
uv run --quiet python "${REPO_ROOT}/tools/lint/ruff_safe.py" $dirs

echo "Running pyright"
uv run --quiet pyright
