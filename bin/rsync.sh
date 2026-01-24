#!/bin/bash
# Safe rsync wrapper for TeleClaude
# Usage: bin/rsync.sh <computer-name>
#
# ALWAYS uses .rsyncignore to protect config.yml, .env, and other local files
# Computer names must be defined in config.yml under remote_computers

set -e

if [ $# -lt 1 ]; then
    echo "Usage: bin/rsync.sh <computer-name>"
    echo ""
    echo "Available computers are defined in config.yml under remote_computers"
    exit 1
fi

COMPUTER_NAME=$1
shift

# Get project root (script is in bin/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Read computer config from config.yml using grep/awk
CONFIG_FILE="$PROJECT_ROOT/config.yml"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: config.yml not found at $CONFIG_FILE"
    exit 1
fi

# Parse YAML to extract computer config
# Look for the computer section (2-space indent) and extract properties (4-space indent)
USER=$(awk "/^  $COMPUTER_NAME:/{flag=1; next} flag && /^    user:/{print \$2; exit} flag && /^  [a-z]/{exit}" "$CONFIG_FILE")
HOST=$(awk "/^  $COMPUTER_NAME:/{flag=1; next} flag && /^    host:/{print \$2; exit} flag && /^  [a-z]/{exit}" "$CONFIG_FILE")
TPATH=$(awk "/^  $COMPUTER_NAME:/{flag=1; next} flag && /^    teleclaude_path:/{print \$2; exit} flag && /^  [a-z]/{exit}" "$CONFIG_FILE")

if [ -z "$USER" ] || [ -z "$HOST" ] || [ -z "$TPATH" ]; then
    echo "Error: Computer \"$COMPUTER_NAME\" not found in config.yml or incomplete configuration"
    echo ""
    echo "Available computers:"
    awk '/^remote_computers:/,/^[a-z]/ {if (/^  [a-z0-9]+:/) print "- " substr($1, 3, length($1)-3)}' "$CONFIG_FILE"
    exit 1
fi

REMOTE="$USER@$HOST:$TPATH"

# Verify .rsyncignore exists
RSYNCIGNORE="$PROJECT_ROOT/.rsyncignore"
if [ ! -f "$RSYNCIGNORE" ]; then
    echo "Error: .rsyncignore not found at $RSYNCIGNORE"
    exit 1
fi

echo "Syncing TeleClaude..."
echo "  Source: $PROJECT_ROOT/"
echo "  Remote: $REMOTE"
echo "  Exclude files: .rsyncignore, .gitignore"
echo ""

# Execute rsync with MANDATORY exclude patterns:
# - .rsyncignore (rsync-specific patterns)
# - .gitignore (using filter syntax for proper gitignore semantics)
rsync -avz --exclude-from="$RSYNCIGNORE" --filter=':- .gitignore' "$@" "$PROJECT_ROOT/" "$REMOTE"

echo ""
echo "✓ Sync complete"
