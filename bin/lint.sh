#!/usr/bin/env sh
set -e  # Exit on first error

dirs="teleclaude bin"

echo "Running lint checks"

echo "Running guardrails"
uv run --quiet python bin/lint/guardrails.py "$@"

echo "Running markdown validation"
uv run --quiet bin/lint/markdown.py

echo "Running resource validation"
uv run --quiet -m teleclaude.cli.telec sync --validate-only --project-root "$(pwd)"

echo "Running ruff format (check)"
uv run --quiet ruff format --check $dirs

echo "Running ruff check"
uv run --quiet ruff check $dirs

echo "Running pyright"
uv run --quiet pyright
