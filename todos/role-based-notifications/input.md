# Role-Based Notifications

## Context

TeleClaude currently has a personal Telegram message script that sends to a single
user. The system lacks multi-person notification routing — when a job completes, a
report is ready, or an alert fires, there's no way to notify people based on their
role or interests.

The `teleclaude.yml` configuration already supports a people structure
(`~/.teleclaude/people/{name}/teleclaude.yml`), and discovery infrastructure exists
(`teleclaude/cron/discovery.py` scans per-person configs). The foundation is there;
the notification layer is missing.

## The Feature

A notification subsystem that routes messages to people based on their configured
role, interests, or explicit subscription to notification channels.

### Envisioned Flow

```
Job/Process produces output
  |
  v
Notification request (channel, content, file?)
  |
  v
Notification router
  +-- Resolve subscribers for channel (from people configs)
  +-- For each subscriber:
      +-- Determine delivery method (Telegram DM, topic message, etc.)
      +-- Send via appropriate adapter
```

### Configuration Surface (per-person teleclaude.yml)

```yaml
# ~/.teleclaude/people/{name}/teleclaude.yml
notifications:
  telegram_chat_id: '123456789'
  channels:
    - idea-miner-reports # receives daily idea analysis
    - maintenance-alerts # receives maintenance job results
    - system-health # receives daemon health alerts
  role: maintainer # coarse-grained role for default routing
```

### Notification Channels (examples)

| Channel            | Trigger                        | Content                    |
| ------------------ | ------------------------------ | -------------------------- |
| idea-miner-reports | Idea miner job completion      | Report file + summary      |
| maintenance-alerts | GitHub maintenance job results | PR links, triage summary   |
| system-health      | Daemon instability detected    | Status + recovery actions  |
| delivery-log       | Work item finalized            | What was shipped + PR link |

### Delivery Methods

- **Telegram DM**: Direct message via bot to personal chat_id
- **Telegram topic**: Message to a group topic (existing adapter)
- **File upload**: `teleclaude__send_file` for reports, logs, artifacts

## Infrastructure to Build

1. **Notification router**: `teleclaude/notifications/router.py` — resolves channel
   subscribers from people configs, dispatches via adapters
2. **Per-person config extension**: Add `notifications:` section to people teleclaude.yml
3. **Discovery extension**: Extend `teleclaude/cron/discovery.py` to find notification
   subscribers (or build parallel discovery for notification configs)
4. **Telegram DM sender**: Generalize existing personal script into a reusable module

## Relationship to Other Work

- **idea-miner**: First consumer. The idea miner job needs to send reports to
  interested people. Without this, it can only send to a hardcoded recipient.
- **github-maintenance-runner**: Second consumer. Maintenance results need routing.
- **System health monitoring**: Future consumer for daemon alerts.

## Design Decisions to Make

1. **Push vs. pull**: Should notifications be pushed by jobs, or should a central
   outbox collect and dispatch?
2. **Channel registration**: Explicit per-person opt-in, or role-based defaults?
3. **Delivery guarantees**: Fire-and-forget, or retry with backoff?
4. **Rate limiting**: Batch notifications to avoid spamming during busy periods?

## Dependencies

- People configuration structure (exists: `~/.teleclaude/people/`)
- Telegram bot with DM capability (exists: personal script)
- `teleclaude__send_file` / `teleclaude__send_result` MCP tools (exist)

## Out of Scope

- Email notifications
- Webhook integrations
- User self-service subscription management
- Notification preferences UI
