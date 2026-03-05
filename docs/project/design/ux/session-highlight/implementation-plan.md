---
id: 'project/design/ux/session-highlight/implementation-plan'
type: 'design'
scope: 'project'
description: 'Implementation plan for explicit reason-driven highlight system.'
---

# Session Highlight Implementation Plan — Design

## Required reads

- @docs/project/design/ux/session-highlight.md
- @docs/project/design/architecture/cache-system.md

## Purpose

Replace the current brittle inference-based highlight detection with an enriched `session_updated` event that carries a `reason` field. The current system compares `last_input` and `last_output_digest` to detect changes; the new system receives the reason directly from the source.

Highlight events are not separate from `session_updated` — they ARE `session_updated`, with semantic meaning attached. Creating a parallel event stream would cause timing chaos and coordination complexity. Instead, we enrich the existing single event path.

## Inputs/Outputs

### Current Architecture

```
┌─────────────────┐    db write     ┌─────────────────┐
│ agent_coordinator│ ──────────────▶│  Database       │
│ (handles hooks)  │                │                 │
└─────────────────┘                 └────────┬────────┘
                                             │ triggers
                                             ▼
                                    ┌─────────────────┐
                                    │  DaemonCache    │
                                    │  (notify)       │
                                    └────────┬────────┘
                                             │ session_updated
                                             ▼
                                    ┌─────────────────┐
                                    │  API Server     │
                                    │  (WebSocket)    │
                                    └────────┬────────┘
                                             │ session_updated (no reason)
                                             ▼
                                    ┌─────────────────┐
                                    │  TUI            │
                                    │  (compare state)│ ◀── Brittle inference
                                    └─────────────────┘
```

**Problem**: TUI must infer what changed by comparing previous vs current session state. This is:

- Brittle: depends on polling timing and field comparison
- Lossy: multiple rapid events collapse into one state diff
- Indirect: the TUI doesn't know WHY state changed

### Target Architecture

```
┌─────────────────┐    notify(reason)  ┌─────────────────┐
│ agent_coordinator│ ─────────────────▶│  DaemonCache    │
│ (knows the WHY)  │                   │  (forwards)     │
└─────────────────┘                    └────────┬────────┘
                                                │
                                                ▼
                                       ┌─────────────────┐
                                       │  API Server     │
                                       │  (WebSocket)    │
                                       └────────┬────────┘
                                                │ session_updated + reason
                                                ▼
                                       ┌─────────────────┐
                                       │  TUI            │
                                       │  (reads reason) │ ◀── Direct, explicit
                                       └─────────────────┘
```

**Solution**: The coordinator owns the "why" and passes it through the existing pipeline. Single event stream, no timing issues.

### SessionUpdateReason type

```python
from typing import Literal

SessionUpdateReason = Literal[
    "user_input",      # User sent input to agent
    "tool_done",       # Agent produced streaming output
    "agent_stopped",   # Agent completed its turn
    "state_change",    # Generic state change (status, title, etc.)
]
```

## Invariants

1. `reason=None` is valid for generic updates and must not trigger any highlight change.
2. Draft and gate must never run in the same worker session.
3. The coordinator is the only component authorized to attach a reason; the cache and API server forward it opaquely.
4. Backwards compatible: existing consumers that omit reason continue to work with `None`.

## Primary flows

### Phase 1: Define Update Reasons

**File: `teleclaude/core/models.py`** (or appropriate location)

Add reason type (see `SessionUpdateReason` above).

### Phase 2: Update Cache Notify Interface

**File: `teleclaude/core/cache.py`** (DaemonCache)

```python
def notify_session_updated(
    self,
    session_id: str,
    reason: SessionUpdateReason | None = None,
) -> None:
    """Notify subscribers that a session was updated.

    Args:
        session_id: The session that changed
        reason: Why it changed (for highlight logic). None for generic updates.
    """
    self._pending_notifications[session_id] = {
        "session_id": session_id,
        "reason": reason,
    }
    # ... existing notification logic ...
```

### Phase 3: Coordinator Passes Reason

**File: `teleclaude/core/agent_coordinator.py`**

- In `handle_user_prompt_submit`: `self.cache.notify_session_updated(session_id, reason="user_input")`
- In `handle_tool_done`: `self.cache.notify_session_updated(session_id, reason="tool_done")`
- In `handle_agent_stop`: `self.cache.notify_session_updated(session_id, reason="agent_stopped")`

### Phase 4: WebSocket Payload Includes Reason

**File: `teleclaude/api_server.py`**

```python
async def _broadcast_session_updated(self, session_id: str, reason: str | None = None) -> None:
    await self._broadcast_to_websockets("session_updated", {
        "session_id": session_id,
        "reason": reason,
    })
```

**File: `teleclaude/api_models.py`**

```python
class SessionUpdatedEvent(BaseModel):
    event: Literal["session_updated"] = "session_updated"
    session_id: str
    reason: Literal["user_input", "tool_done", "agent_stopped", "state_change"] | None = None
```

### Phase 5: TUI Reads Reason Directly

**File: `teleclaude/cli/tui/state.py`** — reducer handles `SESSION_UPDATED` with reason-based highlight logic.

**File: `teleclaude/cli/tui/app.py`** — reads reason from WebSocket event, manages 3-second temp highlight timer for `tool_done`.

### Phase 6: Add Timer Clear Intent

Add `CLEAR_TEMP_HIGHLIGHT` intent and reducer logic. Timer clears only if session is still in `temp_output_highlights`.

### Phase 7: Remove Inference Logic

**File: `teleclaude/cli/tui/views/sessions.py`** — remove `_update_activity_state` and `SESSION_ACTIVITY` dispatch.

**File: `teleclaude/cli/tui/state.py`** — remove `SESSION_ACTIVITY` from `IntentType` and its reducer case.

### Phase 8: State Persistence

```python
@dataclass
class SessionViewState:
    input_highlights: set[str] = field(default_factory=set)
    output_highlights: set[str] = field(default_factory=set)
    temp_output_highlights: set[str] = field(default_factory=set)
```

### Files Changed Summary

| File                                   | Change                                                                   |
| -------------------------------------- | ------------------------------------------------------------------------ |
| `teleclaude/core/models.py`            | Add `SessionUpdateReason` type                                           |
| `teleclaude/core/cache.py`             | Update `notify_session_updated` signature                                |
| `teleclaude/core/agent_coordinator.py` | Pass reason at 3 points                                                  |
| `teleclaude/api_server.py`             | Forward reason in WebSocket payload                                      |
| `teleclaude/api_models.py`             | Update `SessionUpdatedEvent` model                                       |
| `teleclaude/cli/tui/state.py`          | Update reducer, add `CLEAR_TEMP_HIGHLIGHT`, add `temp_output_highlights` |
| `teleclaude/cli/tui/app.py`            | Read reason, manage timers                                               |
| `teleclaude/cli/tui/views/sessions.py` | Remove inference logic                                                   |

### Estimated Complexity

- **Reason type**: Low (one type alias)
- **Cache interface**: Low (add parameter)
- **Coordinator changes**: Low (3 call sites)
- **WebSocket payload**: Low (add field)
- **TUI reducer**: Medium (reason-based logic + timer)
- **Remove inference**: Medium (careful deletion)
- **Testing**: Medium (new test cases)

Total: ~300-400 lines of changes across 8 files.

### Why This Approach

1. **Single event stream**: No parallel event bus, no timing coordination
2. **Cache stays simple**: Just passes through what coordinator tells it
3. **Coordinator owns semantics**: The source of "what happened" attaches meaning
4. **Backwards compatible**: `reason=None` works for generic updates
5. **Minimal API change**: One optional parameter added to existing method

## Failure modes

| Scenario                              | Behavior                                                                                         |
| ------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Coordinator omits reason              | `reason=None` propagates; TUI applies no highlight change. Safe default.                         |
| Timer fires before `agent_stopped`    | `CLEAR_TEMP_HIGHLIGHT` clears temp highlight only. Persistent highlights remain unaffected.      |
| Rapid events collapse at WebSocket    | Each event carries its own reason; TUI reducer applies them in arrival order. No inference needed. |
| Old consumer receives `reason` field  | `reason=None` for generic updates; field is optional. No breaking change.                        |
