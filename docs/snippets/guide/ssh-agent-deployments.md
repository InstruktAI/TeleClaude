---
id: teleclaude/guide/ssh-agent-deployments
type: guide
scope: project
description: Configure SSH agent access for automated git operations and deployments.
requires: []
---

## Goal

- Ensure the daemon has SSH agent access for automated deployments.

## Preconditions

- SSH keys are available on the host.

## Steps

1. Run the daemon as a user service to inherit the SSH agent environment.
2. Use keychain (or equivalent) to persist `SSH_AUTH_SOCK`.
3. Wrap the daemon entrypoint to source the keychain environment before starting.
4. Verify `SSH_AUTH_SOCK` is available in the daemon process.

## Outputs

- Git operations can run without manual key entry.

## Recovery

- If SSH auth fails, reinitialize keychain and confirm environment sourcing.
