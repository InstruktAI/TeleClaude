#!/usr/bin/env bash
# setup-runner.sh — Patch GitHub Actions runner for macOS Keychain access
#
# Run AFTER: ./config.sh && ./svc.sh install
# Purpose:  The runner's LaunchAgent plist ships with SessionCreate=true,
#           which isolates it from the GUI login session's keychain.
#           This script patches that to false and restarts the service.

set -euo pipefail

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

echo ""
echo "=== Credential Check ==="
errors=0

# Claude: OAuth token in macOS Keychain
if security find-generic-password -s "Claude Code-credentials" -w \
     ~/Library/Keychains/login.keychain-db >/dev/null 2>&1; then
  echo "  Claude: OK (Keychain credential readable)"
else
  echo "  Claude: MISSING — run 'claude login' from a GUI terminal session"
  errors=$((errors + 1))
fi

# Codex: file-based auth
if [[ -f "$HOME/.codex/auth.json" ]]; then
  echo "  Codex:  OK ($HOME/.codex/auth.json exists)"
else
  echo "  Codex:  MISSING — run 'codex auth login'"
  errors=$((errors + 1))
fi

# Gemini: file-based auth
if [[ -f "$HOME/.gemini/oauth_creds.json" ]]; then
  echo "  Gemini: OK ($HOME/.gemini/oauth_creds.json exists)"
else
  echo "  Gemini: MISSING — run 'gemini auth login'"
  errors=$((errors + 1))
fi

echo ""
if [[ $errors -gt 0 ]]; then
  echo "WARNING: $errors credential(s) not accessible."
  echo "         Log in from a GUI terminal, then re-run this script to verify."
  exit 1
fi

echo "All credentials verified. Runner is ready for release automation."
