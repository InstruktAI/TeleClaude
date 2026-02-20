---
title: Session Lifecycle Spec — formalizing observability and cleanup
date: 2026-02-20
priority: high
status: open
---

## Context

Memory review identified critical session management patterns that are currently scattered across gotchas and procedures:

- **Codex sessions unobservable until first turn** (Memory #31)
- **end_session is mandatory** (Memory #30)

These patterns reveal a mismatch between orchestrator expectations and actual session behavior. The session lifecycle needs a formal specification that covers:

1. When sessions are observable
2. When state is reliable
3. When cleanup is required
4. Polling vs. notification semantics

## Findings

### Codex Observability Gap

**Problem:** Codex sessions cannot be observed until the first turn completes.

- Native session ID and session file only exist AFTER first turn finishes.
- Calling `get_session_data` before first turn completes returns "session-not-found".
- Orchestrator wrongly interprets this as "session ended" (false negative).

**Impact:**

- Cannot tail early output from Codex workers.
- Blocks orchestrator from knowing if session started successfully.
- Cascades into incorrect state assumptions in next-work machine.

**Current Workaround:** Do not poll `get_session_data` for Codex. Wait for completion notification instead.

### end_session Mandatory

**Problem:** `get_session_data` returning "session file not found" does NOT mean the session is ended.

**Impact:**

- Orphaned sessions if orchestrator assumes "file not found" → "session gone".
- Wasted compute; lost signal from workers.
- State cascades: missing cleanup → missing notifications → missed work.

**Requirement:** Always call `end_session` explicitly per procedure. Use `list_sessions` to verify state when in doubt.

## Scope

Create a formal **Session Lifecycle Specification** that documents:

### 1. Session States

```
SPAWNED → [FIRST_TURN] → OBSERVABLE → [PROCESSING] → ENDED/ERRORED
```

- **SPAWNED:** Session started, ID issued, but session file may not exist yet (Codex case).
- **FIRST_TURN:** Initial execution underway. Observability varies by agent type.
- **OBSERVABLE:** Session file exists, `get_session_data` works, worker is responsive.
- **PROCESSING:** Worker executing tasks, session remains observable.
- **ENDED:** Explicit `end_session` called. Session resources cleaned.
- **ERRORED:** Unexpected termination, timeout, or crash.

### 2. Observability Contract by Agent Type

| Agent Type | Session File | Observable At          | First Turn Data              |
| ---------- | ------------ | ---------------------- | ---------------------------- |
| Claude     | Immediate    | Immediate              | Available immediately        |
| Codex      | After turn 1 | After turn 1 completes | Unavailable until completion |
| Gemini     | Immediate    | Immediate              | Available immediately        |

### 3. Cleanup Requirements

- `end_session` MUST be called explicitly.
- `get_session_data` returning 404 is **NOT** a cleanup signal.
- `list_sessions` is the canonical state source.
- Never assume session is gone without explicit verification.

### 4. Orchestrator Pattern

```
1. Dispatch session
2. For Codex: wait for completion notification (do not poll)
3. For Claude/Gemini: can poll if needed, but notifications preferred
4. Call end_session explicitly when work is complete
5. (Only then is cleanup guaranteed)
```

## Related

- Memory #31: Codex sessions unobservable until first turn
- Memory #30: end_session is mandatory
- docs/project/spec/session-lifecycle.md (new or target file)
- Affects: next-work machine, orchestrator.py, agent lifecycle code
