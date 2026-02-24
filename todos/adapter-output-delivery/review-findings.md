# Review Findings: adapter-output-delivery

REVIEW COMPLETE: adapter-output-delivery

Verdict: REQUEST CHANGES

Findings: 7 (1 Critical, 4 Important, 2 Suggestions)

---

## Critical

### `SESSION_STARTED` event no longer emitted for non-headless sessions

**File:** `teleclaude/core/command_handlers.py:389`, `teleclaude/daemon.py:1099-1135`

Before this change, `command_handlers.create_session` called `db.create_session(...)` then immediately emitted `SESSION_STARTED`. This branch moved emission responsibility to `db.create_session` (via `emit_session_started: bool = True` default) but then suppressed it with `emit_session_started=False`. The separate `event_bus.emit(SESSION_STARTED, ...)` call that previously followed was removed.

The `_bootstrap_session_resources` daemon task (the implied new owner) creates tmux, starts polling, and transitions lifecycle*status to "active", but **never emits `SESSION_STARTED`**. The comment at `daemon.py:1126` — *"TTS session*start is triggered via event_bus (SESSION_STARTED event)"* — documents that TTS startup depends on this event, which now never fires for non-headless sessions.

Subscribers that lose notification for every new regular session:

- `api_server.py:194` — WebSocket clients (`_handle_session_started_event`)
- `hooks/bridge.py:57` — External webhook consumers
- `daemon.py:1018` — Headless snapshot service (`_handle_session_started`)

The `db.py:341` docstring explicitly states: _"If False, caller is responsible for emitting SESSION_STARTED."_ The caller does not emit it.

**Fix:** Emit `SESSION_STARTED` in `_bootstrap_session_resources` after tmux is provisioned (after line 1124), which is the semantically correct moment (session is fully ready). This completes the deferred-emit intent without restoring the premature pre-tmux emission.

---

## Important

### `inspect.isawaitable` guard on always-async `broadcast_user_input`

**File:** `teleclaude/core/agent_coordinator.py:433-441`

`AdapterClient.broadcast_user_input` is `async def` (`adapter_client.py:575`). Calling it always produces a coroutine, which `inspect.isawaitable` always returns `True` for. The guard is unconditionally true and the `import inspect` at the top of the file exists solely for this call. More dangerously: if `broadcast_user_input` is ever replaced with a synchronous method (e.g. a mock or a sync wrapper), the unawaited coroutine would be silently discarded before the `isawaitable` check executes.

**Fix:** Replace lines 433-441 with a direct `await self.client.broadcast_user_input(...)`.

---

### `last_output_digest` computed but never persisted — dedup guard is permanently a no-op

**File:** `teleclaude/core/agent_coordinator.py:755-780`

`_maybe_send_incremental_output` computes `display_digest` at line 755 and compares it against `session.last_output_digest` at line 758 to skip unchanged content. However `display_digest` is never written back: `update_kwargs` at line 771 only conditionally adds `last_tool_done_at`. There is no path in this method that sets `update_kwargs["last_output_digest"]` or calls `db.update_session(session_id, last_output_digest=display_digest)`.

The guard at line 758 evaluates `session.last_output_digest` (always `None` or a stale value) against a freshly computed hash — always unequal — so `send_threaded_output` is called on every invocation regardless of whether content has changed. The requirements note: _"Acceptable given cursor-based reads and digest dedup"_. With the new poller-triggered path calling `trigger_incremental_output` at ~1Hz per threaded session, the broken dedup turns a best-effort refresh into a guaranteed duplicate-update on every tick.

**Fix:** Inside the `if session.last_output_digest != display_digest:` branch, after the successful `send_threaded_output` call, add `update_kwargs["last_output_digest"] = display_digest` to persist the new digest alongside the cursor.

---

### Discord webhook reflection path has zero test coverage

**File:** `teleclaude/adapters/discord_adapter.py:717-802`

`_send_reflection_via_webhook` (~50 lines) and `_get_or_create_reflection_webhook` (~30 lines) are new, non-trivial methods that create Discord webhooks, cache them in-process, and send actor-attributed messages. The success criterion for this feature is: _"On Discord, actor-attributed reflections render via webhook when possible and safely fall back to normal send when not."_

No test in the five changed test files (and confirmed absent in `tests/unit/test_discord_adapter.py`) covers:

1. Webhook path activation when `reflection_actor_name` is set in metadata
2. Graceful fallback to standard bot send when webhook creation fails
3. Cache hit on second call (webhook reuse)
4. `_get_or_create_reflection_webhook` returning `None` when `create_webhook` is absent

Without test coverage, the graceful fallback contract specified by the requirements cannot be verified.

---

### Discord webhook cache not evicted on send failure — permanent reflection degradation per channel

**File:** `teleclaude/adapters/discord_adapter.py:774-802` (cache miss), `discord_adapter.py:730-739` (send failure path)

On success, the webhook object is stored in `_reflection_webhook_cache[channel_id]`. On a send failure (the webhook was deleted, token rotated, etc.), the exception is caught and `None` is returned, but the **stale entry is never evicted** from the cache. Every subsequent reflection to that channel re-uses the stale webhook object, fails with a warning, and falls back to plain bot send — permanently, for the lifetime of the daemon process.

Additionally, when webhook **creation** fails (permission denied, max-webhooks limit reached), nothing is written to the cache. The next reflection call re-enters the miss path, lists webhooks, and retries creation — logging a warning for every single reflection message until process restart.

**Fix (stale entry):** In `_send_reflection_via_webhook`, on exception from `send_fn`, evict the entry: `self._reflection_webhook_cache.pop(channel_id, None)` before returning `None`.

**Fix (creation failure):** On `create_webhook` failure, store a sentinel (e.g. `False`) to suppress repeated creation attempts: `self._reflection_webhook_cache[channel_id] = False`, and check `if cached is not None` → `if cached is not None and cached is not False`.

---

## Suggestions

### Notice drop for non-UI origin logged only at `debug` level — invisible in production

**File:** `teleclaude/core/adapter_client.py:372-383`

When `feedback=True` and `last_input_origin` resolves to a non-UI adapter (e.g. `"api"`, `"hook"`, or empty string), `send_message` returns `None` after emitting a `logger.debug` line. At production log levels, this drop is invisible. A session that has never recorded a UI origin (sessions in early lifecycle stages) will silently drop every notice message. Promote the log to `logger.info` so operators can distinguish intentional origin-only routing from delivery failures.

---

### Build gate "Working tree clean" marked `[x]` despite uncommitted changes to todo docs

**Files:** `todos/adapter-output-delivery/implementation-plan.md` (staged revert of `[x]` → `[ ]`), `todos/adapter-output-delivery/requirements.md` and `todos/adapter-output-delivery/quality-checklist.md` (unstaged reverts)

The build gate at `quality-checklist.md` is checked `[x] Working tree clean`, but at review time the working tree contains staged and unstaged changes that revert the committed todo documents toward their pre-build state. The committed implementation plan (HEAD) has all tasks `[x]`; the staged change un-checks them. These are todo-directory changes that do not affect production code, but the build gate assertion is not accurate.

---

## Verified Fixed (Prior Findings)

- **Double reflection for headless/non-headless** — FIXED. Non-headless: `broadcast_user_input` called before return; headless: delegates to `process_message`. No duplication. ✓
- **Reflection format (missing computer-name)** — REQUIREMENTS UPDATED. The `"TUI @ {computer_name}"` format replaced by actor-attributed reflection propagated from adapters. Requirements updated in HEAD. ✓
- **MCP-origin filter** — REQUIREMENTS UPDATED. MCP input is now intentionally reflected (criteria 7 in committed requirements). `_NON_INTERACTIVE` guard removed by design. ✓
- **Implementation plan tasks unchecked** — FIXED in committed HEAD. All plan tasks are `[x]`. Working tree has a staged revert (see suggestion above). ✓
