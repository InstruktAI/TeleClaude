# Agent Session Lifecycle Specification — Idea

**ID:** 260219-session-lifecycle-spec
**Status:** Idea
**Severity:** Medium
**Source:** memory-review

## Problem

Memories 30 and 31 document critical but scattered session lifecycle gotchas:

- **Memory 30**: `end_session` is mandatory; session-not-found doesn't mean session is gone
- **Memory 31**: Codex sessions are unobservable until first turn completes; orchestrators incorrectly interpret this as session-ended

These are documented but not consolidated into a single reference. Orchestrators and workers repeatedly discover these gotchas the hard way.

## Root Cause

- Session lifecycle behavior differs by agent type (Claude, Codex, Gemini)
- No unified spec describing these asymmetries
- Gotchas are in memory/scattered docs, not in canonical architecture docs

## Proposal

Create `project/spec/agent-lifecycle.md` documenting:

### 1. Session Creation

| Operation             | Behavior                                                       |
| --------------------- | -------------------------------------------------------------- |
| `start_session`       | Creates tmux session, spawns agent process, returns session_id |
| Session file creation | Claude/Gemini: immediate; Codex: after first turn only         |
| Native observability  | Claude/Gemini: immediate; Codex: blocked until first turn      |

### 2. Session Observability Rules

**Claude & Gemini (Immediate):**

- `list_sessions` returns immediately
- `get_session_data` works immediately
- `get_session_data` with session-not-found = session actually ended

**Codex (Delayed):**

- `list_sessions` may not show session until first turn
- `get_session_data` returns "session file not found" until first turn completes
- This is NOT an error — it's expected behavior
- Orchestrators must wait for notification, not poll

### 3. Cleanup Requirements

- **Mandatory**: All sessions must call `end_session` explicitly
- `get_session_data` returning error does NOT mean session is ended
- Skipping `end_session` causes orphaned processes and wasted compute

### 4. Procedure: Safe Session Termination

```
1. Determine agent type (Claude, Codex, Gemini)
2. For Codex: wait for completion notification before querying state
3. Call end_session explicitly
4. Verify with list_sessions that session is gone
```

### 5. Known Gotchas

- Codex session-not-found on day 1 is normal; day 2+ is an error
- `get_session_data` tail queries have response size limits (48KB)
- Session timeout defaults; custom timeouts via config

## Success Criteria

- New orchestrators understand Codex observability model without surprises
- Session cleanup is consistently applied
- No more orphaned sessions from false "session ended" assumptions

## Owner

Recommended for agent architecture documentation.
