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
  echo "Running ruff auto-fix (safe fixes only)"
  ruff check --fix $py_files

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

# Remove empty CLAUDE.md files (created by agent sessions without content)
REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
for claude_md in $(find "$REPO_ROOT" -name "CLAUDE.md" -not -path "*/trees/*" -not -path "*/.git/*" 2>/dev/null); do
  # Strip claude-mem-context tags and whitespace — if nothing remains, delete
  cleaned=$(sed 's/<\/*claude-mem-context>//g' "$claude_md" | tr -d '[:space:]')
  if [ -z "$cleaned" ]; then
    rm -f "$claude_md"
    echo "Removed empty CLAUDE.md: $claude_md"
  fi
done

# Restaging after format is handled by the pre-commit wrapper (.git/hooks/pre-commit)
