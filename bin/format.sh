#!/usr/bin/env sh
. .venv/bin/activate

# If filenames are passed (from pre-commit), format only those files
# Otherwise format entire teleclaude directory
if [ $# -gt 0 ]; then
  files="$@"
  echo "Formatting staged files: $files"
else
  files="teleclaude"
  echo "Formatting all code in teleclaude/"
fi

echo "Running isort"
python -m isort $files

echo "Running black"
black $files
