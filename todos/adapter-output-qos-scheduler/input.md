# Input: adapter-output-qos-scheduler

## User Intent

- Create a new, action-ready todo that consolidates the Telegram cadence/rate-limit discussion.
- Keep the solution pragmatic: prefer platform-native rate limiting where possible and avoid unnecessary custom complexity.
- Investigate a generic path that can support Telegram now and extend to Discord/WhatsApp later.

## Conversation Summary

- Current issue is Telegram output churn and flood-control when many sessions emit concurrently.
- A fixed `3s` cadence per session is only safe at low concurrency; with many active sessions it can exceed Telegram group/channel limits.
- We want output logic to be leading:
  - compute cadence dynamically from active emitting sessions
  - coalesce stale updates (latest wins per session)
  - keep final/completion updates timely
- We want to avoid overbuilding:
  - use python-telegram-bot's built-in rate limiter as baseline
  - add minimal custom layer only where product behavior is not provided by the library (per-session latest-only output coalescing and fairness)

## Expected Deliverable

- A complete todo package with requirements, implementation plan, quality checklist, and evidence-backed research notes that can be executed directly by an implementation agent.
