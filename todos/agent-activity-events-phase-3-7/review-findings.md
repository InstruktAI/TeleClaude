# Review Findings: agent-activity-events-phase-3-7

## Summary

Rename of event vocabulary (`after_model`/`agent_output` → `tool_use`/`tool_done`) and DB columns is mechanically correct and comprehensive. New tests cover event emission and broadcast paths well. Two issues found: one bug and one stale comment.

## Critical

None.

## Important

### 1. `tool_name` coercion produces `"None"` string when absent

**File:** `teleclaude/core/agent_coordinator.py:501`

```python
tool_name = str(payload.raw.get("tool_name") or payload.raw.get("toolName"))
```

When neither key exists in `payload.raw`, this evaluates to `str(None)` → `"None"` (the string). The `tool_name` field will be the literal string `"None"` instead of `None`, which leaks into the `AgentActivityEvent` and downstream WebSocket broadcasts.

**Fix:** Guard the `str()` call:

```python
raw_tool = payload.raw.get("tool_name") or payload.raw.get("toolName")
tool_name = str(raw_tool) if raw_tool else None
```

## Suggestions

### 2. Stale comments in receiver still reference old vocabulary

**File:** `teleclaude/hooks/receiver.py:688,694`

Two comments still reference old event names:

- Line 688: `'after_model' -> 'AfterModel'`
- Line 694: `for direct events like 'agent_output'`

These are cosmetic but create confusion since neither `after_model` nor `agent_output` exist as event types anymore.

## Verdict: REQUEST CHANGES

One Important finding (tool_name bug) needs fixing before merge.
