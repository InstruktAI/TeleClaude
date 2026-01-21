---
id: decision/exit-marker-removal
type: decision
scope: project
description: Architectural decision to move from file-based exit markers to hook-based events.
---

# Decision: Hook-Based Agent Completion

## Context

Early versions of TeleClaude used file markers (e.g., `.tc_done`) to detect when an agent finished a turn. This was brittle and slow.

## Decision

Move to a hook-based architecture (`mcp-wrapper` + `AgentCoordinator`).

## Rationale

1. **Speed**: Hooks are near-instant; polling for files adds latency.
2. **Rich Metadata**: Hooks can pass structured event data (agent name, thinking mode, summary).
3. **Reliability**: Events are written to the `hook_outbox` for durable processing.

## Implementation

- `bin/mcp-wrapper.py` emits `turn-completed` hooks.
- `teleclaude/hooks/receiver.py` captures and routes them.
