# Session Stop Event Hook Design

**Date:** 2026-02-20
**Source:** Lifelog from 12/2/2025 session

## Decision

Add hook mechanism to alert orchestrator when remote cloud sessions complete.

## Mechanism

1. Hook triggered on remote session stop event
2. Hook injects standard string into tmux (user input)
3. Payload format: `session <session_id> finished`
4. Orchestrator interprets message and calls `get_session_data` to inspect output

## Intent

- Orchestrator becomes aware of worker session completion without polling
- Allows context integration of session results into main session
- Replaces passive monitoring with active event-driven notification

## Technical Components

- Existing: `get_session_data` tool for inspection
- New: Hook on remote session stop
- New: tmux message injection for orchestrator pickup
- Integration: Orchestrator context refresh with session output

## Implementation Status

Design discussed, implementation pending.

## Rationale

Fire-and-forget session dispatch currently has no completion signal. Hook-based notification enables orchestrator to react immediately when workers finish.
