#!/usr/bin/env bash
# Check for raw SQL usage without guard markers in database modules
# Usage: scripts/check-raw-sql.sh [--project-root <path>] [paths...]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROJECT_ROOT="${DEFAULT_PROJECT_ROOT}"
SELECTED_PATHS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --project-root requires a path argument" >&2
                exit 2
            fi
            PROJECT_ROOT="$2"
            shift 2
            ;;
        -h|--help)
            cat <<'USAGE'
Usage: check-raw-sql.sh [--project-root <path>] [paths...]
Checks raw SQL usage markers in TeleClaude code.
With paths, checks only selected raw-SQL-owned files.
USAGE
            exit 0
            ;;
        *)
            SELECTED_PATHS+=("$1")
            shift
            ;;
    esac
done

PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"

# Files to check for raw SQL
RAW_SQL_FILES=(
    "teleclaude/core/db/_base.py"
    "teleclaude/core/db/_sync.py"
    "teleclaude/memory/search.py"
    "teleclaude/memory/store.py"
    "teleclaude/memory/context/builder.py"
)
FILES=()

is_raw_sql_file() {
    local rel="$1"
    local owned
    for owned in "${RAW_SQL_FILES[@]}"; do
        if [[ "$rel" == "$owned" ]]; then
            return 0
        fi
    done
    return 1
}

normalize_selected_path() {
    local path="$1"
    if [[ "$path" == "${PROJECT_ROOT}/"* ]]; then
        printf '%s\n' "${path#${PROJECT_ROOT}/}"
    else
        printf '%s\n' "${path#./}"
    fi
}

if [[ ${#SELECTED_PATHS[@]} -eq 0 ]]; then
    for rel in "${RAW_SQL_FILES[@]}"; do
        FILES+=("${PROJECT_ROOT}/${rel}")
    done
else
    for selected in "${SELECTED_PATHS[@]}"; do
        rel="$(normalize_selected_path "$selected")"
        if is_raw_sql_file "$rel"; then
            FILES+=("${PROJECT_ROOT}/${rel}")
        fi
    done
fi

found_violations=0

for file in "${FILES[@]}"; do
    if [[ ! -f "$file" ]]; then
        continue
    fi

    # Pattern 1: import of text from sqlalchemy
    while IFS=: read -r line_num line_content; do
        if [[ -n "$line_num" && ! "$line_content" =~ "guard: raw-sql" ]]; then
            echo "ERROR: $file:$line_num: Raw SQL import without 'guard: raw-sql' marker"
            echo "  $line_content"
            found_violations=1
        fi
    done < <(grep -n -E 'from sqlalchemy.*import.*text' "$file" 2>/dev/null || true)

    # Pattern 2: text(, execute(...), executescript(...), or cursor.execute(...) used for SQL.
    # Match common SQL execution primitives while skipping non-SQL text helpers.
    while IFS=: read -r line_num line_content; do
        if [[ -n "$line_num" && ! "$line_content" =~ "guard: raw-sql" ]]; then
            # Skip false positives like read_text, write_text, _text, Text\(|Context
            if [[ "$line_content" =~ (read_text|write_text|_text|Text\(|Context) ]]; then
                continue
            fi
            echo "ERROR: $file:$line_num: Raw SQL without 'guard: raw-sql' marker"
            echo "  $line_content"
            found_violations=1
        fi
    done < <(grep -n -E '(^\s*text\(|\btext\s*\(|\bexecute\(\"|\.execute\(\"|\.executescript\(|cursor\.execute\()' "$file" 2>/dev/null || true)
done

if [[ $found_violations -eq 1 ]]; then
    echo ""
    echo "To allow raw SQL, add '# guard: raw-sql' comment to the line."
    echo "Raw SQL is only permitted for PRAGMAs, migrations, and sync helpers."
    exit 1
fi

exit 0
