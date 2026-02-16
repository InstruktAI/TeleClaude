# Review Findings: help-desk-control-room

## Review Scope

Reviewed 9 source files and 5 test files changed since branch diverged from main.
All 80 branch-relevant tests pass. 19 pre-existing failures on main (TUI, command handlers) are unrelated.

---

## Critical

None.

---

## Important

### I1: `close_channel` and `delete_channel` are now identical

**File:** `teleclaude/adapters/discord_adapter.py:185-237`

Both methods perform `thread.delete()` with identical error handling and logging. This violates the code duplication policy.

**Fix:** Delegate `close_channel` to `delete_channel`:

```python
async def close_channel(self, session: "Session") -> bool:
    return await self.delete_channel(session)
```

### I2: Redundant OR in `_maybe_send_incremental_output`

**File:** `teleclaude/core/agent_coordinator.py:635`

```python
is_enabled = is_threaded_output_enabled_for_session(session) or is_threaded_output_enabled(agent_key)
```

`is_threaded_output_enabled_for_session` already calls `is_threaded_output_enabled(session.active_agent)` internally. The second clause only differs when `agent_key` (from payload) differs from `session.active_agent`. If this dual-check is intentional (payload agent vs session agent), it needs a comment explaining why. If not, remove the redundant clause.

### I3: Missing test coverage for `ensure_channel` edge cases

**File:** `tests/unit/test_discord_adapter.py`

Three untested paths in `DiscordAdapter.ensure_channel`:

1. Early return when `thread_id` is already set (idempotency guard)
2. No-op when `help_desk_channel_id` is None (dev/test mode)
3. Thread creation + DB refresh path

These are new code paths that should have unit tests.

---

## Suggestions

### S1: `last_input_origin` vs immutable origin for feature gating

**File:** `teleclaude/core/feature_flags.py:42`

`is_threaded_output_enabled_for_session` uses `session.last_input_origin` which changes on every input from a different adapter. For Discord help desk sessions this is stable in practice, but if a CLI/API/hook input changes the origin mid-session, threaded output would toggle off. Consider using the session's creation origin for this gate in a follow-up (requires adding `origin_adapter` field).

### S2: `close_channel` doesn't clear `thread_id` metadata

**File:** `teleclaude/adapters/discord_adapter.py:197`

After `delete_fn()`, `discord_meta.thread_id` remains set. If the session is ever reused, `ensure_channel` would skip thread creation. In practice, closed sessions don't receive output, so this is theoretical. Consider clearing metadata post-delete for correctness.

### S3: `reopen_channel` behavior after delete

**File:** `teleclaude/adapters/discord_adapter.py:203-219`

`reopen_channel` still attempts `edit(archived=False, locked=False)`, which is impossible after deletion. Not blocking — `reopen_channel` is never called in production code. If it's ever used, it will return `False` gracefully (thread not found).

---

## Logging Hygiene

No ad-hoc debug probes found. All logging uses the structured logger. Log messages updated correctly to reflect new behavior ("delete" instead of "close").

---

## Test Hygiene

No prose-lock tests. No exact-string assertions on documentation wording. Tests verify behavior (delete, metadata, suppression) not implementation details.

---

## Verdict: APPROVE

The implementation correctly satisfies all five requirements:

- **R1**: `char_offset` promoted to session-level column with migration; adapter-agnostic access
- **R2**: Gemini hardcheck removed; experiment config gates agent access
- **R3**: All Discord sessions use threaded output via `is_threaded_output_enabled_for_session`
- **R4**: `close_channel` deletes thread instead of archiving
- **R5**: `broadcast=True` enables cross-platform threaded output mirroring

No deferrals exist. All implementation plan tasks are checked. Build gates are complete. The Important findings (I1-I3) are code quality improvements that should be addressed but do not block merge.
