# Requirements: adapter-output-qos-scheduler

## Goal

Implement an adapter-aware output QoS system that prevents Telegram flood-control churn under high concurrency, while remaining extensible to Discord and WhatsApp without adapter-specific rewrites.

## Scope

## In scope

- Add adapter-level output QoS abstraction with policy hooks.
- Integrate PTB rate limiting in Telegram adapter startup path.
- Add output coalescing and fairness scheduling for Telegram output updates (legacy `send_output_update` and threaded `send_threaded_output`).
- Compute release cadence from configured budget and active emitting sessions.
- Preserve final-update correctness (`is_final` and completion messages).
- Add observability for queue depth, effective cadence, coalescing, and rate-limit retries.

## Out of scope

- Rewriting all message command paths across all adapters in this todo.
- Distributed cross-process rate coordination (future: Redis token bucket if multiple daemons share one bot token).
- Hard enablement of strict Discord/WhatsApp pacing before metrics confirm need.

## Background Constraints

- Telegram official guidance indicates roughly:
  - `~20 messages/minute` in the same group
  - `~1 message/second` per chat
- PTB provides optional `AIORateLimiter` and a `BaseRateLimiter` extension point.
- Current TeleClaude output fanout is serialized and awaited; naive sleeps in lane code can stall unrelated adapter work.

## Functional Requirements

1. **FR1: Generic QoS abstraction**
   - Introduce a reusable output scheduler abstraction with adapter policy inputs.
   - Policy selects coalescing behavior, pacing budget, and priority handling.

2. **FR2: Telegram PTB baseline limiter**
   - Enable PTB `rate_limiter(...)` in Telegram `Application.builder()` path.
   - Add dependency support for PTB rate-limiter extra.

3. **FR3: Latest-only coalescing (per session)**
   - While a session is waiting to emit, retain only the latest pending output payload for that session.
   - Discard superseded non-final payloads without user-visible errors.

4. **FR4: Dynamic cadence from active emitters**
   - Compute effective output budget and pacing at runtime:
     - `effective_output_mpm = max(1, min(group_mpm - reserve_mpm, floor(group_mpm * output_budget_ratio)))`
     - `global_tick_s = ceil_to_100ms(60 / effective_output_mpm)`
     - `target_session_tick_s = ceil_to_100ms(max(min_session_tick_s, global_tick_s * active_emitting_sessions))`
   - Apply policy caps/floors (`min_session_tick_s`, optional `max_session_tick_s`).

5. **FR5: Priority behavior**
   - `is_final` payloads and completion-critical updates are priority class `high`.
   - Priority updates must be flushed immediately or in the next available slot.

6. **FR6: Non-blocking shared pipeline**
   - QoS waiting must not block non-Telegram adapter lanes.
   - No inline `sleep` in shared adapter fanout path.

7. **FR7: Threaded + non-threaded parity**
   - Telegram throttling/coalescing policy applies consistently to:
     - legacy output update path
     - threaded incremental output path

8. **FR8: Adapter rollout mode**
   - Telegram starts in `strict` mode (paced + coalesced).
   - Discord starts in `coalesce_only` mode (no hard cap initially).
   - WhatsApp policy stub is present but disabled until adapter-specific limits are confirmed.

9. **FR9: Backward-compatible safety**
   - Existing retry/backoff wrappers remain as fallback during rollout.
   - No regressions in output_message_id continuity or threaded char offset logic.

## Non-Functional Requirements

- **NFR1: Predictability**: bounded queue growth through coalescing (latest-only).
- **NFR2: Fairness**: no single hot session starves others.
- **NFR3: Operability**: clear metrics/logs for tuning and incident diagnosis.
- **NFR4: Simplicity**: rely on platform/library limiters first; keep custom logic narrow and product-focused.

## Configuration Requirements

- Add adapter QoS config namespace (exact schema to finalize in implementation):
  - `telegram.qos.enabled`
  - `telegram.qos.group_mpm` (default `20`)
  - `telegram.qos.output_budget_ratio` (default `0.8`)
  - `telegram.qos.reserve_mpm` (default `4`)
  - `telegram.qos.min_session_tick_s` (default `3.0`)
  - `telegram.qos.rounding_ms` (default `100`)
  - `discord.qos.mode` (`off|coalesce_only|strict`)
  - `whatsapp.qos.mode` (`off` initially)

## Success Criteria

- [ ] Telegram no longer enters sustained flood-control retry loops during multi-session output bursts in stress test.
- [ ] With `N >= 10` active emitting sessions, queue depth remains stable and stale payload growth does not become unbounded.
- [ ] Final outputs are delivered promptly and not lost behind normal update backlog.
- [ ] Threaded Telegram sessions retain correct message continuity (no duplicate split artifacts, no broken offsets).
- [ ] Discord behavior unchanged by default except optional coalescing mode when enabled.
- [ ] Operator metrics are sufficient to tune budgets without code changes.

## Risks

- Misconfigured budget can over-throttle UX or under-throttle Telegram.
- Partial rollout without observability can hide starvation in edge sessions.
- Tight coupling with threaded output internals can introduce regressions if not covered by tests.

## Source Evidence

- PTB `AIORateLimiter`: https://docs.python-telegram-bot.org/en/v22.1/telegram.ext.aioratelimiter.html
- PTB `BaseRateLimiter`: https://docs.python-telegram-bot.org/en/v22.1/telegram.ext.baseratelimiter.html
- Telegram FAQ limits: https://core.telegram.org/bots/faq
- Discord rate limits: https://discord.com/developers/docs/topics/rate-limits
- Discord support guidance: https://support-dev.discord.com/hc/en-us/articles/6223003921559-My-Bot-is-Being-Rate-Limited
- WhatsApp throughput preview docs: https://meta-preview.internationalmessaging.com/en-gb/docs/whatsapp/business-platform/changelog
