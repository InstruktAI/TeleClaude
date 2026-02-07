#!/usr/bin/env bash
# Check for raw SQL usage without noqa markers in db.py and hooks/receiver.py
# Usage: scripts/check-raw-sql.sh

set -e

# Files to check for raw SQL
FILES=(
    "teleclaude/core/db.py"
    "teleclaude/hooks/receiver.py"
)

found_violations=0

for file in "${FILES[@]}"; do
    if [[ ! -f "$file" ]]; then
        continue
    fi

    # Pattern 1: import of text from sqlalchemy
    while IFS=: read -r line_num line_content; do
        if [[ -n "$line_num" && ! "$line_content" =~ "noqa: raw-sql" ]]; then
            echo "ERROR: $file:$line_num: Raw SQL import without 'noqa: raw-sql' marker"
            echo "  $line_content"
            found_violations=1
        fi
    done < <(grep -n -E 'from sqlalchemy.*import.*text' "$file" 2>/dev/null || true)

    # Pattern 2: text( used for SQL (but not read_text, write_text, etc.)
    # Match lines starting with text( or having = text( or .exec(text(
    while IFS=: read -r line_num line_content; do
        if [[ -n "$line_num" && ! "$line_content" =~ "noqa: raw-sql" ]]; then
            # Skip false positives like read_text, write_text, _text, Context
            if [[ "$line_content" =~ (read_text|write_text|_text|Text\(|Context) ]]; then
                continue
            fi
            echo "ERROR: $file:$line_num: Raw SQL without 'noqa: raw-sql' marker"
            echo "  $line_content"
            found_violations=1
        fi
    done < <(grep -n -E '(^\s*text\(|\btext\s*\()' "$file" 2>/dev/null || true)
done

if [[ $found_violations -eq 1 ]]; then
    echo ""
    echo "To allow raw SQL, add '# noqa: raw-sql' comment to the line."
    echo "Raw SQL is only permitted for PRAGMAs, migrations, and sync helpers."
    exit 1
fi

exit 0
