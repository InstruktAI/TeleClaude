#!/usr/bin/env bash
# setup-runner.sh — Patch GitHub Actions runner for macOS Keychain access
#
# Run AFTER: ./config.sh && ./svc.sh install
# Purpose:  The runner's LaunchAgent plist ships with SessionCreate=true,
#           which isolates it from the GUI login session's keychain.
#           This script patches that to false and restarts the service.

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Guards ---

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: This script only supports macOS (got $(uname -s))" >&2
  exit 1
fi

# --- Locate runner plist ---

PLIST_DIR="$HOME/Library/LaunchAgents"
mapfile -t PLISTS < <(find "$PLIST_DIR" -name "actions.runner.*.plist" 2>/dev/null)

if [[ ${#PLISTS[@]} -eq 0 ]]; then
  echo "ERROR: No runner plist found in $PLIST_DIR" >&2
  echo "       Run './config.sh && ./svc.sh install' first." >&2
  exit 1
fi

if [[ ${#PLISTS[@]} -gt 1 ]]; then
  echo "ERROR: Multiple runner plists found:" >&2
  printf '  %s\n' "${PLISTS[@]}" >&2
  echo "       Remove extras or specify which to patch." >&2
  exit 1
fi

PLIST="${PLISTS[0]}"
LABEL=$(plutil -extract Label raw "$PLIST" 2>/dev/null || basename "$PLIST" .plist)
echo "Runner plist: $PLIST"
echo "Service label: $LABEL"

# --- Patch SessionCreate ---

CURRENT=$(plutil -extract SessionCreate raw "$PLIST" 2>/dev/null || echo "missing")

if [[ "$CURRENT" == "false" || "$CURRENT" == "0" ]]; then
  echo "SessionCreate already false — skipping patch."
else
  echo "Patching SessionCreate: $CURRENT -> false"
  plutil -replace SessionCreate -bool false "$PLIST"
  echo "Plist patched."

  # Restart the service to pick up the change
  echo "Restarting runner service..."
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  sleep 1
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "Runner service restarted."
fi

# --- Verify credentials ---
#
# Delegated to teleclaude.runtime.agent_preflight, keyed exhaustively by each
# canonical agent's registry-declared check kind (Keychain service, file
# presence, or Keychain-or-file) — see teleclaude/agent_registry.py. Adding a
# canonical agent registers its check here automatically; this script no
# longer hand-lists agents.
PREFLIGHT_PYTHON="$INSTALL_DIR/.venv/bin/python"
if [[ ! -x "$PREFLIGHT_PYTHON" ]]; then
  PREFLIGHT_PYTHON="python3"
fi
env PYTHONPATH="$INSTALL_DIR" "$PREFLIGHT_PYTHON" -m teleclaude.runtime.agent_preflight
