---
id: teleclaude/procedure/rsync-development
type: procedure
scope: project
description: Fast iteration workflow using bin/rsync.sh and remote daemon restarts.
requires:
  - ../policy/daemon-availability.md
---

Steps
1) Check remote status with ssh -A user@host 'cd $HOME/apps/TeleClaude && git status'.
2) Sync changes with bin/rsync.sh <computer-name> (use names from config.yml).
3) Restart the daemon remotely with make restart and verify with make status.
4) Tail logs with instrukt-ai-logs teleclaude -f while iterating.

Outputs
- Remote computer running the latest local changes with minimal downtime.
