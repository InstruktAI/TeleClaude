# Codex session observability carve-out in next-work

## Problem

Codex sessions (and likely Gemini sessions) have fundamentally different observability from Claude:

- Claude sessions are observable immediately (session file exists at creation)
- Codex sessions are not observable until the **first turn completes**
- Calling `get_session_data()` before first turn returns "session not found"
- Orchestrators wrongly interpret this as "session ended" and trigger cleanup

Memory #31 documents this. It's a gotcha that keeps resurfacing in orchestration logic.

## Opportunity

Add an explicit carve-out in the next-work state machine and orchestration procedures for non-Claude agents:

1. **Do not poll Codex/Gemini with get_session_data() before first turn completes**
2. **Wait for the completion notification instead** — this is the signal that the session is observable
3. **Document this in next-work and orchestration instructions**
4. **Potentially add session-type awareness to list_sessions** for easier diagnosis

## Scope

- Update next-work documentation with agent-type-specific polling rules
- Update orchestration examples to show correct handling of non-Claude agents
- Consider adding `agent_type` field to list_sessions output for visibility

## Success criteria

- Orchestrators never falsely kill Codex workers due to observability lag
- Documentation is clear about which agent types are immediately observable
- No more false "session ended" scenarios in logs
