#!/usr/bin/env sh
set -e  # Exit on first error

. .venv/bin/activate

dirs="teleclaude"

echo "Running lint checks"

echo "Running pylint"
pylint $dirs

echo "Running mypy"
mypy $dirs
