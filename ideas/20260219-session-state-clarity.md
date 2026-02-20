# Session State Assumptions — Gotcha Consolidation

**ID:** 20260219-session-state-clarity
**Status:** Idea
**Severity:** Medium
**Frequency:** Multiple gotchas (reported 2026-02-11)

## The Problem

Multiple session management gotchas exist because of hidden assumptions about session state visibility and lifecycle:

1. **Codex sessions invisible until first turn** (#31):
   - Codex sessions cannot be observed mid-turn
   - Native session ID and session file only exist after first turn completes
   - Calling `get_session_data` before that returns "session-not-found"
   - Orchestrators wrongly interpret this as session ended

2. **end_session must be explicit** (#30):
   - `get_session_data` returning "Session file not found" does NOT mean session is ended
   - Skipping `end_session` based on assumptions causes orphaned sessions, wasted compute, cascading state issues
   - Assumption-based cleanup is not safe

## Root Cause

- **Incomplete mental model:** Each agent type (Claude, Codex, Gemini) has different observability windows
- **Silent failures:** Missing sessions don't error; they're treated as "success" by buggy assumptions
- **Coupling:** Orchestrator assumptions about session lifecycle are brittle and agent-type-specific

## Current Evidence of Failure

- Codex workers: procedure explicitly says "do not poll with get_session_data until first turn completes"
- Orchestrators: no explicit carve-out for Codex observability lag
- Session cleanup: assumption-based, not explicit

## Solutions to Explore

1. **Documentation refresh**
   - Update next-work procedure with explicit Codex observability carve-out
   - Add decision tree: "What does 'session not found' mean?" per agent type
   - Document valid session lifecycle states and transitions

2. **API clarity**
   - `get_session_data` should return explicit status codes, not just file-not-found
   - `list_sessions` should be the source of truth for "is session running?"
   - Add optional timeout parameter to `get_session_data` that polls until ready

3. **Automation**
   - Orchestrator template: automatic wait-for-observability before first poll
   - Session cleanup guard: always call `list_sessions` before deciding to `end_session`

## Impact

- **Reliability:** Eliminate orphaned sessions and cascading cleanup failures
- **Clarity:** Agent type differences become explicit rather than hidden
- **Trust:** Session state assumptions become provable, not guessed

## Related

- Memory #31: "Codex sessions unobservable until first turn completes"
- Memory #30: "end_session is mandatory — never assume session is gone"
- AI-to-AI Troubleshooting procedure
- Orchestration procedure (next-work state machine)

## Next Step

Audit next-work procedure for all session assumptions; add explicit per-agent-type observability rules.
