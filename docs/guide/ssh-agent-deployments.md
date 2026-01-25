---
id: teleclaude/guide/ssh-agent-deployments
type: guide
scope: project
description: Configure SSH agent access for automated git operations and deployments.
---

# Ssh Agent Deployments — Guide

## Goal

- Ensure the daemon has SSH agent access for automated deployments.

- SSH keys are available on the host.

1. Run the daemon as a user service to inherit the SSH agent environment.
2. Use keychain (or equivalent) to persist `SSH_AUTH_SOCK`.
3. Wrap the daemon entrypoint to source the keychain environment before starting.
4. Verify `SSH_AUTH_SOCK` is available in the daemon process.

- Git operations can run without manual key entry.

- If SSH auth fails, reinitialize keychain and confirm environment sourcing.

- TBD.

- TBD.

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
