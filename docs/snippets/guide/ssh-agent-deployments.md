---
id: teleclaude/guide/ssh-agent-deployments
type: guide
scope: project
description: Configure SSH agent access for automated git operations and deployments.
requires: []
---

Guide
- Run the daemon as a user service when it needs SSH agent access.
- Use keychain (or equivalent) to provide a persistent SSH_AUTH_SOCK.
- Wrap the daemon entrypoint to source the keychain environment before starting.
- Verify SSH_AUTH_SOCK is available to the daemon process.
