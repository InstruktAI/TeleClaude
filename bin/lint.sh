#!/usr/bin/env sh
. .venv/bin/activate

dirs="teleclaude"

echo "Running lint checks"

echo "Running pylint"
pylint --enable=C0415 --fail-on=C0415 $dirs

echo "Running mypy"
mypy $dirs
