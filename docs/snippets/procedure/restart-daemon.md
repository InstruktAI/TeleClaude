---
description: Controlled daemon restart with verification and log checks.
id: teleclaude/procedure/restart-daemon
requires:
- teleclaude/policy/daemon-availability
scope: project
type: procedure
---

Steps
1) Run make restart.
2) Verify the service is running with make status.
3) Check recent logs with instrukt-ai-logs teleclaude --since 10m.

Outputs
- Daemon process restarted and confirmed healthy.