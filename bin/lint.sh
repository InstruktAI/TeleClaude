#!/usr/bin/env sh
set -e  # Exit on first error

. .venv/bin/activate

dirs="teleclaude bin"

echo "Running lint checks"

echo "Running guardrails"
python bin/lint/guardrails.py "$@"

echo "Running markdown validation"
python bin/lint/markdown.py

echo "Running ruff format (check)"
ruff format --check $dirs

echo "Running ruff check"
ruff check $dirs

echo "Running pyright"
pyright
