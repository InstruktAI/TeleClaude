# Research: adapter-output-qos-scheduler

## Research Date

- 2026-02-26

## Primary Sources

1. Python Telegram Bot docs: `AIORateLimiter`
   - https://docs.python-telegram-bot.org/en/v22.1/telegram.ext.aioratelimiter.html
2. Python Telegram Bot docs: `BaseRateLimiter`
   - https://docs.python-telegram-bot.org/en/v22.1/telegram.ext.baseratelimiter.html
3. Telegram Bot FAQ (official)
   - https://core.telegram.org/bots/faq
4. Discord API docs: Rate Limits (official)
   - https://discord.com/developers/docs/topics/rate-limits
5. Discord Developer Support article (official)
   - https://support-dev.discord.com/hc/en-us/articles/6223003921559-My-Bot-is-Being-Rate-Limited
6. Meta docs preview: WhatsApp throughput/page limits
   - https://meta-preview.internationalmessaging.com/en-gb/docs/whatsapp/business-platform/changelog

## Key Findings

### Telegram / PTB

- PTB provides `AIORateLimiter`, but it is optional and requires the rate-limiter extra (`pip install "python-telegram-bot[rate-limiter]"`).
- PTB documents `BaseRateLimiter` for custom strategies and states different methods may need different handling.
- PTB's built-in limiter is baseline transport control; it does not provide product-specific "latest-only per session output" semantics by itself.
- Telegram FAQ states rough limits around:
  - about 30 messages/second to different users
  - about 20 messages/minute to the same group
  - about 1 message/second to the same chat

### Discord

- Discord enforces per-route and global limits and returns headers (`X-RateLimit-*`, `Retry-After`) for clients to adapt.
- Discord docs explicitly advise not hard-coding limits and to parse headers.
- The Discord developer support article cites a global bot ceiling (commonly 50 req/s), with caveats and route behavior.

### WhatsApp (Meta)

- Meta preview docs describe throughput and pair-rate constraints for WhatsApp messaging.
- Exact throughput behavior is plan/tier-dependent and should be policy-driven, not globally hard-coded into shared logic.

## Implications for TeleClaude

1. Telegram should use PTB rate-limiter support as first-line protection.
2. TeleClaude still needs a thin adapter-level output coalescing/fairness layer:
   - to prevent stale backlog growth under high output demand
   - to preserve user-facing behavior (latest output state per session)
3. Scheduler architecture should be generic, with adapter-specific policy modules:
   - Telegram: strict pacing + coalescing
   - Discord: start coalescing-only (library handles transport RL)
   - WhatsApp: policy slot ready, enable once exact constraints are finalized

## Local Code Evidence (Current State)

- Global poll cadence is unified (`output_cadence_s`) at poller level:
  - `teleclaude/core/output_poller.py:83`
- Polling coordinator always awaits `send_output_update`, then triggers incremental output:
  - `teleclaude/core/polling_coordinator.py:885`
  - `teleclaude/core/polling_coordinator.py:894`
- UI fanout is serialized across adapters:
  - `teleclaude/core/adapter_client.py:122`
- Telegram adapter start does not currently wire PTB rate limiter:
  - `teleclaude/adapters/telegram_adapter.py:727`
- Telegram currently relies on retry wrappers + mutable pending-edit context:
  - `teleclaude/adapters/telegram/message_ops.py:251`
  - `teleclaude/adapters/telegram/message_ops.py:379`
