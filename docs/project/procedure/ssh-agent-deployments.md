---
id: project/procedure/ssh-agent-deployments
type: procedure
scope: project
description: Configure SSH agent access for automated git operations and deployments.
---

# SSH Agent Deployments — Procedure

## Goal

Ensure the daemon has SSH agent access for automated deployments.

## Preconditions

- SSH keypair available for the deployment target.
- Ability to run the daemon as a user service.

## Steps

1. Run the daemon as a user service to inherit the SSH agent environment.
2. Use keychain (or equivalent) to persist `SSH_AUTH_SOCK` across reboots and session changes.
3. Wrap the daemon entrypoint to source the keychain environment before starting.
4. Verify `SSH_AUTH_SOCK` is available in the daemon process with `ssh-add -l`.

## Outputs

- Daemon can perform git operations without interactive prompts.
- `SSH_AUTH_SOCK` visible in the daemon environment.

## Recovery

- Starting the daemon from a context that lacks `SSH_AUTH_SOCK` (e.g., a raw cron job or a fresh launchd without environment sourcing).
- Forgetting to unlock keys after a reboot — keychain persists the socket but keys may still require passphrase entry.
