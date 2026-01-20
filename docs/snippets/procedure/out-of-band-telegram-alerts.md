---
id: teleclaude/procedure/out-of-band-telegram-alerts
type: procedure
scope: project
description: Send Telegram alerts when the daemon is down using standalone scripts.
requires:
  - ../policy/daemon-availability.md
---

Steps
1) Use bin/send_telegram.py for a one-off message with a chat id or username.
2) Use bin/notify_agents.py for structured alerts with auto-topic selection and backoff.
3) If backoff needs reset after a healthy run, call bin/notify_agents.py --reset.

Outputs
- Alert delivered even when MCP/daemon interfaces are unavailable.
- Backoff state persisted under logs/monitoring.
