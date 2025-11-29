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

REMOTE=$1
shift

# Get project root (script is in bin/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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
