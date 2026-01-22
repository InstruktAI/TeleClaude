---
id: procedure/ssh-agent-keychain
type: procedure
scope: global
description: Procedure for configuring persistent SSH agent access for the daemon.
---

## Goal

- Ensure the daemon has persistent SSH agent access for automated git operations.

## Preconditions

- Linux host with systemd user services available.

## Steps

1. Install keychain: `sudo apt-get install keychain`.
2. Add to shell config: `eval $(keychain --eval --quiet --agents ssh id_ed25519)`.
3. Run the daemon as a user systemd service so it inherits the keychain environment.
4. Use a wrapper that sources `~/.keychain/$(hostname)-sh` before starting the daemon.
5. SSH into the machine after reboot to unlock the key once.

## Outputs

- The daemon can perform git pulls/pushes without manual key entry.

## Recovery

- If git operations fail, re-unlock the keychain and confirm the wrapper is sourcing the keychain file.
