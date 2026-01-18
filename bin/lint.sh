#!/usr/bin/env sh
set -e  # Exit on first error

. .venv/bin/activate

dirs="teleclaude bin"

echo "Running lint checks"

echo "Running guardrails"
python scripts/guardrails.py "$@"

echo "Running ruff format (check)"
ruff format --check $dirs

echo "Running ruff check"
ruff check $dirs

echo "Running pyright"
pyright
