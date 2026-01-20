---
id: teleclaude/policy/daemon-availability
type: policy
scope: project
description: The TeleClaude daemon must stay up; restarts must be brief and verified.
requires: []
---

Policy
- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.
- After any change, restart the daemon using make restart and verify with make status.
- Do not use make stop during normal development; reserve it for emergencies only.
