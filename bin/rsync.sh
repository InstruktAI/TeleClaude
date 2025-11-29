#!/bin/bash
# Safe rsync wrapper for TeleClaude
# Usage: bin/rsync.sh <user@host:path> [additional rsync args]
#
# ALWAYS uses .rsyncignore to protect config.yml, .env, and other local files

set -e

if [ $# -lt 1 ]; then
    echo "Usage: bin/rsync.sh <user@host:path> [additional rsync args]"
    echo ""
    echo "Example: bin/rsync.sh morriz@raspberrypi.local:/home/morriz/apps/TeleClaude/"
    exit 1
fi

REMOTE_ARG=$1
shift

# Get project root (script is in bin/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Resolve shorthand computer names (convenience shortcuts)
# If REMOTE_ARG looks like a computer name (no @ or :), resolve it
if [[ ! "$REMOTE_ARG" =~ [@:] ]]; then
    # Convert to lowercase for case-insensitive matching
    REMOTE_LOWER=$(echo "$REMOTE_ARG" | tr '[:upper:]' '[:lower:]')

    # Convenience shortcuts for known computers
    # These are NOT a source of truth - just shortcuts to avoid typing full paths
    case "$REMOTE_LOWER" in
        raspi)
            REMOTE="morriz@raspberrypi.local:/home/morriz/apps/TeleClaude/"
            ;;
        raspi4)
            REMOTE="morriz@raspi4.local:/home/morriz/apps/TeleClaude/"
            ;;
        *)
            echo "Error: Unknown computer shortcut '$REMOTE_ARG'"
            echo "Available shortcuts: raspi, raspi4"
            echo "Or use full remote path: user@host:/path/"
            exit 1
            ;;
    esac
else
    # Already a full remote path
    REMOTE="$REMOTE_ARG"
fi

# Verify .rsyncignore exists
RSYNCIGNORE="$PROJECT_ROOT/.rsyncignore"
if [ ! -f "$RSYNCIGNORE" ]; then
    echo "Error: .rsyncignore not found at $RSYNCIGNORE"
    exit 1
fi

echo "Syncing TeleClaude..."
echo "  Source: $PROJECT_ROOT/"
echo "  Remote: $REMOTE"
echo "  Exclude file: $RSYNCIGNORE"
echo ""

# Execute rsync with MANDATORY exclude-from
rsync -avz --exclude-from="$RSYNCIGNORE" "$@" "$PROJECT_ROOT/" "$REMOTE"

echo ""
echo "✓ Sync complete"
