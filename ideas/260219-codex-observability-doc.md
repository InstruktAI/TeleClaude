# Codex Session Observability Documentation — Idea

**ID:** 260219-codex-observability-doc
**Status:** Idea
**Severity:** Medium
**Source:** memory-review

## Problem

Memory 31 documents that Codex sessions don't create native session files until after their first turn completes. This asymmetry confuses orchestrators:

- Claude/Gemini: session observable immediately
- Codex: session unobservable until first turn completes
- Orchestrator misinterprets session-not-found as "session ended" and prematurely cleans up

This is particularly dangerous because the cleanup (`end_session`) occurs while the actual Codex session is still running.

## Root Cause

- Codex's subprocess model differs from the other agents
- No explicit guidance on polling vs. notification patterns per agent type
- The `next-work` state machine may need a Codex-specific carve-out

## Proposal

Create `project/spec/agent-behaviors/codex-observability.md` with:

### 1. Why Codex is Different

- Codex sessions don't have native session files until the agent responds
- This is by design, not a bug
- Orchestrators cannot poll on Codex workers; they must wait for notifications

### 2. Observation Timeline

```
T=0: start_session returns session_id
T=0 to T=N: Codex agent is running, but session file doesn't exist
T=N: Agent completes first turn, session file is written
T=N+: session observable via get_session_data, list_sessions
```

### 3. Orchestrator Rules

**For Claude/Gemini workers:**

- Poll with `get_session_data` is safe
- If session-not-found, session is actually ended
- Can be proactive in monitoring

**For Codex workers:**

- DO NOT POLL with `get_session_data` before first turn
- Session-not-found during first turn is expected, not an error
- Wait for completion notification to observe state
- Only after first turn is session observable

### 4. next-work State Machine Carve-out

The `next-work` orchestrator needs logic like:

```python
if worker_agent_type == "codex":
    # Don't call get_session_data until after first turn
    wait_for_notification()
else:
    # Safe to poll
    monitor_with_get_session_data()
```

### 5. Debugging Codex Session Issues

- If worker hangs: check tmux session manually (`tmux list-sessions`, `tmux capture-pane`)
- Don't rely on list_sessions() during first turn
- Codex worker output only available after first turn

## Success Criteria

- Orchestrators understand Codex observability model upfront
- next-work machine includes Codex-specific handling
- No more premature session cleanup on Codex workers

## Owner

Recommended for next-work procedure and agent behavior specs.
