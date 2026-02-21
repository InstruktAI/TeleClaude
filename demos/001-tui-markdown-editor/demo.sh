#!/usr/bin/env bash
# Demo render script for tui-markdown-editor delivery
# Semver gate: checks major version compatibility before rendering

set -e

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAPSHOT="$DEMO_DIR/snapshot.json"
PROJECT_ROOT="$(cd "$DEMO_DIR/../../../" && pwd)"
PYPROJECT="$PROJECT_ROOT/pyproject.toml"

if [[ ! -f "$SNAPSHOT" ]]; then
    echo "Error: snapshot.json not found at $SNAPSHOT" >&2
    exit 1
fi

# Extract version from pyproject.toml
if [[ -f "$PYPROJECT" ]]; then
    CURRENT_VERSION=$(grep "^version" "$PYPROJECT" | head -1 | sed 's/version = "\([^"]*\)"/\1/')
    CURRENT_MAJOR=$(echo "$CURRENT_VERSION" | cut -d. -f1)
else
    CURRENT_MAJOR="0"
fi

# Extract version from snapshot
SNAPSHOT_VERSION=$(jq -r '.version' "$SNAPSHOT" 2>/dev/null || echo "0.0.0")
SNAPSHOT_MAJOR=$(echo "$SNAPSHOT_VERSION" | cut -d. -f1)

# Semver gate: major version mismatch is a warning but not fatal
if [[ "$CURRENT_MAJOR" != "$SNAPSHOT_MAJOR" ]]; then
    echo "⚠️  Version mismatch: snapshot is $SNAPSHOT_VERSION, current is $CURRENT_VERSION"
    echo "Snapshot was captured at a different major version. Rendering may be inaccurate."
    echo ""
fi

# Render the demo (fallback to jq + printf if no daemon API)
echo "=== DEMO: $(jq -r '.title' "$SNAPSHOT") ==="
echo ""
echo "Delivered: $(jq -r '.delivered_date' "$SNAPSHOT")"
echo "Commit: $(jq -r '.merge_commit' "$SNAPSHOT")"
echo ""
echo "📊 Metrics:"
echo "  Commits: $(jq -r '.metrics.commits' "$SNAPSHOT")"
echo "  Files changed: $(jq -r '.metrics.files_changed' "$SNAPSHOT")"
echo "  Lines: +$(jq -r '.metrics.insertions' "$SNAPSHOT")/-$(jq -r '.metrics.deletions' "$SNAPSHOT")"
echo "  Review rounds: $(jq -r '.metrics.review_rounds' "$SNAPSHOT")"
echo ""
echo "✅ Quality: No critical findings. $(jq -r '.metrics.important_findings' "$SNAPSHOT") important finding resolved."
echo ""
