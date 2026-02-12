# Telegram Fallback Audit (2026-02-12)

Follow-up execution todo:

- `todos/telegram-adapter-hardening/`
- `todos/fallback-fail-fast-hardening/` (cross-cutting contract/fail-fast cleanup)

Scope audited:

- teleclaude/adapters/telegram_adapter.py
- teleclaude/adapters/telegram/channel_ops.py
- teleclaude/adapters/telegram/message_ops.py
- teleclaude/adapters/telegram/input_handlers.py
- teleclaude/adapters/telegram/callback_handlers.py
- teleclaude/core/adapter_client.py (Telegram lane/route behavior)
- teleclaude/utils/**init**.py (retry policy)

## Fallback Inventory (where + why + behavior)

1. `teleclaude/adapters/telegram_adapter.py:171`

- Trigger: missing `topic_id` or channel create failure.
- Fallback: `ensure_channel()` retries by clearing `topic_id` + output message id, then creates channel again.
- Why: recover stale/broken topic mapping.
- Risk: broad `except Exception` can mask root exception class.

2. `teleclaude/adapters/telegram_adapter.py:209`

- Trigger: lane error containing `"message thread not found"` or `"topic_deleted"`.
- Fallback: `recover_lane_error()` resets Telegram metadata (`topic_id`, message ids, offset), recreates topic, retries task.
- Why: self-heal deleted/missing topic.
- Risk: if retry fails, returns `None` (soft failure).

3. `teleclaude/adapters/telegram/message_ops.py:123`

- Trigger: missing Telegram metadata or missing `topic_id`.
- Fallback: `send_message()` logs debug and returns `""` (drop send).
- Why: avoid crashing when topic not ready.
- Risk: output can disappear silently at UI level unless upstream notices empty id.

4. `teleclaude/adapters/telegram/message_ops.py:397`

- Trigger: same as above for files.
- Fallback: `send_file()` returns `""`.
- Why: same resilience.
- Risk: silent artifact drop.

5. `teleclaude/adapters/telegram/message_ops.py:180`

- Trigger: Telegram error text contains `"message thread not found"`.
- Fallback: convert to `TimeoutError` so retry decorator treats it retryable.
- Why: treat topic-readiness race as transient.

6. `teleclaude/adapters/telegram/channel_ops.py:111`

- Trigger: no `FORUM_TOPIC_CREATED` signal within 5s.
- Fallback: `_wait_for_topic_ready()` logs warning, marks topic ready anyway, proceeds.
- Why: avoid deadlock on missing lifecycle event.
- Risk: proceeds on potentially invalid topic state.

7. `teleclaude/adapters/telegram/message_ops.py:285`

- Trigger: edit hit `RetryAfter` or transient network errors.
- Fallback: return `True` (keep existing message id; retry later on next update path).
- Why: avoid duplicate output messages.
- Risk: stale UI appears “successful” while edit didn’t happen yet.

8. `teleclaude/adapters/telegram/message_ops.py:491`

- Trigger: menu edit failures.
- Fallback: only “not found/can't edit” returns `False` (recreate); most other BadRequest/network/unknown errors return `True`.
- Why: avoid duplicate menu spam.
- Risk: unknown failures are treated as success and can hide persistent failure.

9. `teleclaude/adapters/telegram/input_handlers.py:169`

- Trigger: session lookup fails for topic message.
- Fallback: for whitelisted user + thread, tries orphan-topic delete.
- Why: clean dangling topics.
- Risk: repeated delete attempts if topic already invalid/deleted.

10. `teleclaude/adapters/telegram/input_handlers.py:396`

- Trigger: `topic_closed` event with no mapped session.
- Fallback: try orphan-topic delete.
- Why: cleanup.
- Risk: same repeated invalid-delete pattern.

11. `teleclaude/adapters/telegram_adapter.py:890`

- Trigger: command requires session but none found.
- Fallback: if owned topic -> delete orphan and return; else send error message.
- Why: enforce topic/session consistency.
- Risk: aggressive cleanup on uncertain ownership heuristic.

12. `teleclaude/adapters/telegram_adapter.py:883`

- Trigger: ownership check.
- Fallback logic: “owned by this bot” inferred only from topic title containing `@computer`/`$computer`.
- Why: avoid cross-bot deletion.
- Risk: title-based heuristic is weak; wrong positives/negatives.

13. `teleclaude/adapters/telegram/channel_ops.py:232`

- Trigger: orphan delete fails.
- Fallback: logs warning only, no state marker/backoff.
- Why: non-fatal cleanup.
- Risk: same failing delete may be retried forever by callers.

14. `teleclaude/adapters/telegram/callback_handlers.py:132`

- Trigger: malformed/unknown callback data.
- Fallback: silent return.
- Why: ignore invalid callback payloads.
- Risk: no user feedback for bad callback state.

15. `teleclaude/adapters/telegram/callback_handlers.py:208`

- Trigger: missing transcript/session/agent.
- Fallback: return or show user error message; on exception logs + user error edit.
- Why: degrade gracefully for artifact download path.

16. `teleclaude/core/adapter_client.py:613`

- Trigger: UI lane ensure_channel failure.
- Fallback: log blocking-output error and return `None` for lane.
- Why: avoid crash of whole fanout.
- Risk: adapter output dropped.

17. `teleclaude/core/adapter_client.py:1033`

- Trigger: origin adapter missing channel id.
- Fallback: if origin requires channel -> raise; otherwise set `origin_channel_id=""`.
- Why: allow originless flows.
- Risk: empty channel id sentinel can mask misconfigured origin in non-UI paths.

18. `teleclaude/utils/__init__.py:21`

- Trigger: command retry wrapper.
- Fallback policy: retry only rate-limit/network classes; all others are non-retryable (immediate raise with debug log).
- Why: avoid retrying hard logic errors.
- Important for `Topic_id_invalid`: treated non-retryable; hammering is from repeated callers, not retry loop retries.

## Specific suspect: fallback when no known Telegram channel ID

1. `teleclaude/adapters/telegram/message_ops.py:127` and `teleclaude/adapters/telegram/message_ops.py:401`

- No `topic_id` => send is skipped and returns empty string.

2. `teleclaude/adapters/telegram_adapter.py:171`

- Missing `topic_id` => tries to create topic.

3. `teleclaude/core/adapter_client.py:613`

- If ensure/create fails, lane returns `None` (output blocked for that adapter).

## Most likely cause of `Topic_id_invalid` hammering

1. Confirmed: invalid-topic delete path is called from multiple places:

- `teleclaude/adapters/telegram/input_handlers.py:169`
- `teleclaude/adapters/telegram/input_handlers.py:396`
- `teleclaude/adapters/telegram_adapter.py:922`
- all end up in `_delete_orphan_topic()` -> `_delete_forum_topic_with_retry()`.

2. Confirmed: `Topic_id_invalid` is non-retryable (`teleclaude/utils/__init__.py:107`), so each call logs and exits.

3. Inference from code flow: hammering happens because callers keep invoking delete on subsequent updates/events for same stale topic, with no suppression/backoff/cache of “already invalid”.
