#!/usr/bin/env sh
set -e  # Exit on first error

. .venv/bin/activate

dirs="teleclaude bin"

echo "Running lint checks"

echo "Running pylint"
# Pylint exit codes are bitmask: 1=fatal, 2=error, 4=warning, 8=refactor, 16=convention, 32=usage
# We only fail on fatal(1) or error(2), so mask is 3
pylint --ignore=mcp-wrapper.py $dirs || exit_code=$?
if [ "${exit_code:-0}" -ne 0 ] && [ $((exit_code & 3)) -ne 0 ]; then
    echo "Pylint found errors (exit code: $exit_code)"
    exit 1
fi

echo "Running mypy"
mypy $dirs
