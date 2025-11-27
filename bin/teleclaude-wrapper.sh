#!/bin/bash
# Source keychain SSH agent environment
if [ -f ~/.keychain/$(hostname)-sh ]; then
    source ~/.keychain/$(hostname)-sh
fi
# Execute daemon
exec /home/morriz/apps/TeleClaude/.venv/bin/python -m teleclaude.daemon
