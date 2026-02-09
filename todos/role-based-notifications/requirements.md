# Requirements: Role-Based Notifications

## Goal

Build a notification routing subsystem that sends job outputs, reports, and alerts to people based on their explicit channel subscriptions in per-person teleclaude.yml, delivered via an outbox worker.

## Problem Statement

TeleClaude has a personal Telegram script that sends to a single hardcoded user. When jobs complete, reports are ready, or alerts fire, there's no multi-person routing. The per-person config infrastructure exists (`~/.teleclaude/people/`) and discovery scans it, but the notification delivery layer is missing.

## Scope

### In scope

1. **Notification outbox** — SQLite table for pending notifications, delivery worker picks up and sends.
2. **Notification router** — resolve channel subscribers from people configs, write to outbox.
3. **Delivery worker** — background loop that processes outbox rows with retry and failure isolation.
4. **Per-person config extension** — `notifications` section with explicit channel subscriptions.
5. **Discovery extension** — find notification subscribers from per-person configs.
6. **Telegram DM sender** — generalize existing personal script into reusable module.

### Out of scope

- Email notifications.
- Webhook integrations.
- User self-service subscription management.
- Notification preferences UI.
- Web push notifications.
- Auto-subscription of any kind. All subscriptions are explicit opt-in.

## Functional Requirements

### FR1: Notification outbox

- SQLite table `notification_outbox` in existing `teleclaude.db`.
- Columns: `id`, `channel`, `recipient_email`, `content`, `file_path` (optional), `status` (pending/delivered/failed), `created_at`, `delivered_at`, `attempt_count`, `next_attempt_at`, `last_error`.
- Follows existing hook outbox pattern (lock → deliver → retry).

### FR2: Notification router

- `send_notification(channel, content, file=None)` — resolves subscribers for channel, writes one outbox row per subscriber.
- Subscribers resolved from per-person config `notifications.channels` list.
- Jobs call the router; the router never delivers directly.

### FR3: Delivery worker

- Background loop processes pending outbox rows.
- Per-row delivery via configured delivery method (Telegram DM, topic, file upload).
- Retry with backoff on transient failures.
- Failure of one delivery does not block others.
- Delivery failures logged with context.

### FR4: Per-person config

```yaml
notifications:
  telegram_chat_id: '123456789'
  channels:
    - idea-miner-reports
    - maintenance-alerts
    - system-health
```

### FR5: Subscription model

- **Explicit opt-in only.** Every person subscribes to channels in their config. No role-based auto-subscription. No defaults.
- Roles gate what channels a person is _allowed_ to subscribe to (permission boundary), not what they receive.
- If you're not subscribed, you don't get it.

### FR6: Delivery methods

- **Telegram DM**: Direct message to personal `telegram_chat_id`.
- **Telegram topic**: Message to group topic (existing adapter).
- **File upload**: Via `teleclaude__send_file` for reports and artifacts.

### FR7: Discovery

- Extend or parallel existing `discovery.py` to find notification subscribers.
- Scan per-person configs for `notifications` section.
- Build channel → subscriber mapping.

## Non-functional Requirements

1. Outbox delivery with retry (not fire-and-forget).
2. Rate limiting: batch notifications during busy periods to avoid spam.
3. Delivery failures logged but do not block the producing job.

## Acceptance Criteria

1. Notification router resolves subscribers for a named channel.
2. Router writes outbox rows, not direct delivery.
3. Delivery worker picks up and delivers pending rows.
4. Failed deliveries are retried with backoff.
5. Telegram DM delivery sends to configured `telegram_chat_id`.
6. Per-person config with `notifications.channels` is parsed correctly.
7. Unsubscribed people receive nothing regardless of role.
8. Delivery failure for one subscriber does not block others.
9. Existing Telegram adapter behavior unaffected.

## Dependencies

- **config-schema-validation** — per-person config validation.
