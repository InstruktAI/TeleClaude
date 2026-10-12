---
description: 'Send Telegram alerts when the daemon is down using standalone scripts.'
visibility: 'public'
---

# Out Of Band Telegram Alerts — Procedure

## Required reads

- @docs/local/policy/daemon-availability.md

## Goal

- Send Telegram alerts when the daemon or `telec`/API surface is unavailable.

## Preconditions

<!-- planned-change:master-owned-providers -->

- Telegram bot token configured for the alert scripts.

<!-- change:master-owned-providers -->

- Run on the master. The alert scripts read the master's `telegram` section, the
  only one in the fleet (`local/projects/teleclaude/spec/teleclaude-config`,
  scope), and send only when that section's effective `enabled` holds.

<!-- /planned-change:master-owned-providers -->

## Steps

1. Use `bin/send_telegram.py` for a one-off ops message to the configured username (`TELEGRAM_ALERT_USERNAME`).
2. Use `bin/send_telegram.py` for ops-only alerts to the Telegram supergroup.

Note: these scripts are not wired by default; you must schedule them (cron/launchd/systemd) for automated alerts.

## Outputs

- Alert delivered without relying on the daemon.
- Backoff state persisted under `logs`.

## Recovery

<!-- planned-change:master-owned-providers -->

- If delivery fails, verify bot token and `TELEGRAM_ALERT_USERNAME`, then retry with `bin/send_telegram.py`.

<!-- change:master-owned-providers -->

- If delivery fails, verify on the master that `telegram` is enabled and that its bot token and `TELEGRAM_ALERT_USERNAME` resolve, then retry with `bin/send_telegram.py`.

<!-- /planned-change:master-owned-providers -->
