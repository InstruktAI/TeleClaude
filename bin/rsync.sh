#!/bin/bash
# Safe rsync wrapper for TeleClaude
# Usage: bin/rsync.sh <computer-name>
#
# ALWAYS uses .rsyncignore to protect config.yml, .env, and other local files
# Computer names must be declared under remote_computers in the machine configuration

set -e

if [ $# -lt 1 ]; then
    echo "Usage: bin/rsync.sh <computer-name>"
    echo ""
    echo "Available computers are declared under remote_computers in the machine configuration"
    exit 1
fi

COMPUTER_NAME=$1
shift

# Get project root (script is in bin/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Read the named remote computer from the machine configuration through telec.
if ! REMOTE_JSON="$("$PROJECT_ROOT/bin/telec" config computer get computer.remote_computers --format json 2>/dev/null)"; then
    echo "Error: no remote computers are configured on this computer"
    echo "Declare them under remote_computers in the machine configuration (telec config computer get)"
    exit 1
fi

REMOTE_FIELDS="$(python3 -c '
import json, sys
name = sys.argv[1]
computers = json.load(sys.stdin)["computer"]["remote_computers"] or []
match = next((c for c in computers if c.get("name") == name), None)
if match is None or not all(match.get(k) for k in ("user", "host", "teleclaude_path")):
    print("Available computers:", file=sys.stderr)
    for computer in computers:
        print("- " + str(computer.get("name")), file=sys.stderr)
    sys.exit(1)
print(match["user"])
print(match["host"])
print(match["teleclaude_path"])
' "$COMPUTER_NAME" <<<"$REMOTE_JSON")" || {
    echo "Error: Computer \"$COMPUTER_NAME\" not found in remote_computers or incomplete configuration"
    exit 1
}
{
    read -r REMOTE_USER
    read -r HOST
    read -r TPATH
} <<<"$REMOTE_FIELDS"

REMOTE="$REMOTE_USER@$HOST:$TPATH"

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
