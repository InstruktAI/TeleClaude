# Implementation Plan: telegram-adapter-hardening

## Overview

Serial execution by concern. Each phase is independently verifiable and produces an atomic commit.

## Phase 1: Ingress Contract Tightening

### Task 1.1: Remove sentinel coercion for `project_path`

**File(s):** `teleclaude/core/command_mapper.py`

- [ ] Lines 60, 177, 241: replace `project_path=metadata.project_path or ""` with explicit pass-through of `None`.
- [ ] Update `CreateSessionCommand` to accept `Optional[str]` for `project_path` if not already.

### Task 1.2: Restrict help-desk routing to role-based jail only

**File(s):** `teleclaude/core/command_handlers.py`

- [ ] Lines 321-329: remove the `if not project_path` block that defaults to `help-desk`.
- [ ] When `project_path` is missing and no role-based jail applies, return explicit failure to caller.
- [ ] Preserve lines 307-319 (explicit non-admin role jail) unchanged.

### Task 1.3: Align callers to new contract

- [ ] Grep callers of `CreateSessionCommand` and verify they handle `None` / failure correctly.
- [ ] Update tests for `create_session` to cover: valid path, role-jailed, missing path (error).

## Phase 2: Session Data Contract

### Task 2.1: Add explicit source field to `SessionDataPayload`

**File(s):** `teleclaude/core/command_handlers.py`

- [ ] Add `source: str` to `SessionDataPayload` TypedDict with values: `"transcript"`, `"tmux_fallback"`, `"pending"`.
- [ ] `_tmux_fallback_payload`: set `source="tmux_fallback"`.
- [ ] `_pending_transcript_payload`: set `source="pending"`.
- [ ] Normal transcript return: set `source="transcript"`.

### Task 2.2: Align MCP callers

- [ ] Check `get_session_data` tool handler for any `messages == ""` checks; replace with `source` field branching.

## Phase 3: Telegram Delivery Contract

### Task 3.1: Fix send_message return contract

**File(s):** `teleclaude/adapters/telegram/message_ops.py`

- [ ] Line 130: return `None` instead of `""` when `topic_id` is not ready.
- [ ] Update return type annotation from `str` to `str | None` if needed.
- [ ] Check callers for truthy checks on return value (should already handle `None`).

## Phase 4: Orphan Topic Cleanup Suppression

### Task 4.1: Add cooldown-based suppression for repeated invalid-topic deletes

**File(s):** `teleclaude/adapters/telegram/channel_ops.py`, `teleclaude/adapters/telegram_adapter.py`

- [ ] Add `_delete_suppression: dict[int, float]` tracking `topic_id → last_attempt_timestamp`.
- [ ] In `_delete_orphan_topic`, skip if `topic_id` was attempted within cooldown window (60s).
- [ ] Log skipped attempts at debug level with reason.
- [ ] Prune stale entries from suppression dict periodically (e.g., on each call, drop entries older than 5min).

## Phase 5: Ownership Check Hardening

### Task 5.1: Cross-reference DB for delete ownership

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [ ] In `_topic_owned_by_this_bot` (line 883): query `db.get_sessions_by_adapter_metadata("telegram", "topic_id", topic_id)` as primary ownership signal.
- [ ] If DB returns a session for this topic, it's owned. If no session but title matches, log warning and still consider owned (backward compat).
- [ ] If neither DB nor title match, return `False`.
- [ ] Make `_topic_owned_by_this_bot` async (callers already in async context).

## Phase 6: Parse-Entities Error Hardening

### Task 6.1: Make parse-entities fallback explicit

**File(s):** `teleclaude/adapters/telegram/message_ops.py`

- [ ] Line 302: after `can't parse entities` detection, add explicit fallback action (retry without parse_mode, or skip edit with structured log).
- [ ] Emit structured log with fields: `session_id`, `message_id`, `parse_mode`, `action_taken`.
- [ ] Ensure no duplicate footer/message emission on parse failure path.

## Verification

- [ ] `make lint` passes.
- [ ] `make test` passes.
- [ ] Manual smoke: create session without project_path from MCP → expect explicit error.
- [ ] Manual smoke: close orphan topic twice rapidly → second attempt suppressed.
- [ ] Manual smoke: `get_session_data` on active session → response includes `source` field.
