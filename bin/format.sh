#!/usr/bin/env sh
. .venv/bin/activate

dirs="teleclaude"

echo "Formatting all code"

echo "Running isort"
python -m isort $dirs

echo "Running black"
black $dirs
