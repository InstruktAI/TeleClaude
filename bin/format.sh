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

py_files=""
if [ $# -gt 0 ]; then
  for file in "$@"; do
    case "$file" in
      *.py) py_files="$py_files $file" ;;
    esac
  done
else
  py_files="$files"
fi

if [ -n "$py_files" ]; then
  echo "Running ruff import-sort (fix)"
  ruff check --select I --fix $py_files

  echo "Running ruff format"
  ruff format $py_files
fi

# Markdown formatting (prettier)
md_files=""
if [ $# -gt 0 ]; then
  for file in "$@"; do
    case "$file" in
      *.md) md_files="$md_files $file" ;;
    esac
  done
else
  md_files="$(find docs -name '*.md' -print) README.md AGENTS.md"
fi

if [ -n "$md_files" ]; then
  if command -v prettier >/dev/null 2>&1; then
    echo "Running prettier on markdown"
    prettier --write $md_files
  elif command -v npx >/dev/null 2>&1; then
    echo "Running prettier via npx on markdown"
    npx --yes prettier --write $md_files
  else
    echo "ERROR: prettier not found (install prettier or ensure npx is available)."
    exit 1
  fi
fi

# Auto-add formatted files back to staging area (pre-commit hook)
if [ $# -gt 0 ]; then
  git add $files
fi
