---
description: 'Send Telegram alerts when the daemon is down using standalone scripts.'
id: 'project/procedure/out-of-band-telegram-alerts'
scope: 'project'
type: 'procedure'
---

# Out Of Band Telegram Alerts — Procedure

## Required reads

- @docs/project/policy/daemon-availability.md

## Goal

- Send Telegram alerts when the daemon or MCP tools are unavailable.

## Preconditions

- Telegram bot token configured for the alert scripts.

## Steps

1. Use `bin/send_telegram.py` for a one-off ops message to the configured username (`TELEGRAM_ALERT_USERNAME`).
2. Use `bin/send_telegram.py` for ops-only alerts to the Telegram supergroup.

Note: these scripts are not wired by default; you must schedule them (cron/launchd/systemd) for automated alerts.

## Outputs

- Alert delivered without relying on the daemon.
- Backoff state persisted under `logs`.

## Recovery

- If delivery fails, verify bot token and `TELEGRAM_ALERT_USERNAME`, then retry with `bin/send_telegram.py`.
