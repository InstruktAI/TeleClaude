#!/bin/bash
# Resolve install dir from this script location so it works under systemd.
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Ensure relative venv path resolves and venv tools are preferred.
cd "$INSTALL_DIR"
export PATH=".venv/bin:$PATH"
# Source keychain SSH agent environment
if [ -f ~/.keychain/$(hostname)-sh ]; then
    source ~/.keychain/$(hostname)-sh
fi
# Execute daemon
exec $INSTALL_DIR/.venv/bin/python -m teleclaude.daemon
