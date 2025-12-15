#!/usr/bin/env sh
. .venv/bin/activate

# If filenames are passed (from pre-commit), format only those files
# Otherwise format entire teleclaude directory
if [ $# -gt 0 ]; then
  files="$@"
  echo "Formatting staged files: $files"
else
  files="teleclaude bin tests"
  echo "Formatting all code in teleclaude/, bin/, tests/"
fi

echo "Running ruff import-sort (fix)"
ruff check --select I --fix $files

echo "Running ruff format"
ruff format $files

# Auto-add formatted files back to staging area (pre-commit hook)
if [ $# -gt 0 ]; then
  git add $files
fi
