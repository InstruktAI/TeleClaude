---
id: procedure/ssh-agent-keychain
type: procedure
scope: global
description: Procedure for configuring persistent SSH agent access for the daemon.
---

# SSH Agent Configuration

## Requirement
The daemon needs SSH agent access for automated git operations (pulls, pushes) during Redis-based deployments.

## Setup (Linux)
1. **Install Keychain**: `sudo apt-get install keychain`.
2. **Shell Config**: Add `eval $(keychain --eval --quiet --agents ssh id_ed25519)` to `.zshrc`/`.bashrc`.
3. **User Service**: Run the daemon as a **user systemd service** (`systemctl --user`) so it inherits the keychain environment.
4. **Wrapper Script**: Use a wrapper that sources `~/.keychain/$(hostname)-sh` before starting the python process.
5. **Unlock**: SSH into the machine once after reboot to unlock the key; Keychain persists it for the daemon.
