---
description: Send Telegram alerts when the daemon is down using standalone scripts.
id: teleclaude/procedure/out-of-band-telegram-alerts
requires:
  - teleclaude/policy/daemon-availability
scope: project
type: procedure
---

## Goal

- Send Telegram alerts when the daemon or MCP tools are unavailable.

## Preconditions

- Telegram bot token configured for the alert scripts.

## Steps

1. Use `bin/send_telegram.py` for a one-off message with a chat id or username.
2. Use `bin/notify_agents.py` for structured alerts with auto-topic selection and backoff.
3. After a healthy run, reset backoff with `bin/notify_agents.py --reset`.

## Outputs

- Alert delivered without relying on the daemon.
- Backoff state persisted under `logs/monitoring`.

## Recovery

- If delivery fails, verify bot token and chat id, then retry with `bin/send_telegram.py`.
