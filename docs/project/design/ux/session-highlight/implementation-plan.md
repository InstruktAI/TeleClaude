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
- @docs/project/spec/event-types.md

## Overview

Replace the current brittle inference-based highlight detection with an enriched `session_updated` event that carries a `reason` field. The current system compares `last_input` and `last_output_digest` to detect changes; the new system receives the reason directly from the source.

## Key Insight

Highlight events are not separate from `session_updated` — they ARE `session_updated`, with semantic meaning attached. Creating a parallel event stream would cause timing chaos and coordination complexity. Instead, we enrich the existing single event path.

## Current Architecture

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

## Target Architecture

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

## Implementation Steps

### Phase 1: Define Update Reasons

**File: `teleclaude/core/models.py`** (or appropriate location)

Add reason type:

```python
from typing import Literal

SessionUpdateReason = Literal[
    "user_input",      # User sent input to agent
    "agent_output",    # Agent produced streaming output
    "agent_stopped",   # Agent completed its turn
    "state_change",    # Generic state change (status, title, etc.)
]
```

### Phase 2: Update Cache Notify Interface

**File: `teleclaude/core/cache.py`** (DaemonCache)

Update the notify method signature to accept an optional reason:

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
    # Store reason with the notification
    self._pending_notifications[session_id] = {
        "session_id": session_id,
        "reason": reason,
    }
    # ... existing notification logic ...
```

### Phase 3: Coordinator Passes Reason

**File: `teleclaude/core/agent_coordinator.py`**

#### 3.1 On user input

In `handle_user_prompt_submit`:

```python
async def handle_user_prompt_submit(self, context: AgentEventContext) -> None:
    # ... existing code that updates session ...

    # Notify with reason
    self.cache.notify_session_updated(session_id, reason="user_input")
```

#### 3.2 On agent output

In `handle_agent_output`:

```python
async def handle_agent_output(self, context: AgentEventContext) -> None:
    # ... existing code ...

    # Notify with reason
    self.cache.notify_session_updated(session_id, reason="agent_output")
```

#### 3.3 On agent stop

In `handle_agent_stop`:

```python
async def handle_agent_stop(self, context: AgentEventContext) -> None:
    # ... existing code ...

    # Notify with reason
    self.cache.notify_session_updated(session_id, reason="agent_stopped")
```

### Phase 4: WebSocket Payload Includes Reason

**File: `teleclaude/api_server.py`**

Update WebSocket broadcast to include reason:

```python
async def _broadcast_session_updated(
    self,
    session_id: str,
    reason: str | None = None,
) -> None:
    """Broadcast session update to WebSocket clients."""
    await self._broadcast_to_websockets("session_updated", {
        "session_id": session_id,
        "reason": reason,  # None for generic updates
    })
```

**File: `teleclaude/api_models.py`**

Update or add WebSocket event model:

```python
class SessionUpdatedEvent(BaseModel):
    """WebSocket event for session updates."""
    event: Literal["session_updated"] = "session_updated"
    session_id: str
    reason: Literal["user_input", "agent_output", "agent_stopped", "state_change"] | None = None
```

### Phase 5: TUI Reads Reason Directly

**File: `teleclaude/cli/tui/state.py`**

Update `SESSION_UPDATED` intent to carry reason:

```python
# In reducer
if t is IntentType.SESSION_UPDATED:
    session_id = intent.payload["session_id"]
    reason = intent.payload.get("reason")

    if reason == "user_input":
        # Set input highlight, clear output highlight
        state.sessions.input_highlights.add(session_id)
        state.sessions.output_highlights.discard(session_id)

    elif reason == "agent_output":
        # Clear input highlight, set temporary output highlight
        state.sessions.input_highlights.discard(session_id)
        state.sessions.output_highlights.discard(session_id)
        state.sessions.temp_output_highlights.add(session_id)

    elif reason == "agent_stopped":
        # Clear input highlight, set persistent output highlight
        state.sessions.input_highlights.discard(session_id)
        state.sessions.output_highlights.add(session_id)
        state.sessions.temp_output_highlights.discard(session_id)

    # reason=None or "state_change": no highlight changes

    return state
```

**File: `teleclaude/cli/tui/app.py`**

Update WebSocket event handler:

```python
async def _handle_websocket_event(self, event: dict) -> None:
    event_type = event.get("event")

    if event_type == "session_updated":
        session_id = event["session_id"]
        reason = event.get("reason")

        self.controller.dispatch(Intent(
            IntentType.SESSION_UPDATED,
            {"session_id": session_id, "reason": reason}
        ))

        # Handle 3-second timer for streaming output
        if reason == "agent_output":
            self._start_temp_highlight_timer(session_id)
        elif reason == "agent_stopped":
            self._cancel_temp_highlight_timer(session_id)
```

#### Timer implementation

```python
def _start_temp_highlight_timer(self, session_id: str) -> None:
    """Start 3-second timer for temporary output highlight."""
    self._cancel_temp_highlight_timer(session_id)

    async def clear_after_delay():
        await asyncio.sleep(3.0)
        self.controller.dispatch(Intent(
            IntentType.CLEAR_TEMP_HIGHLIGHT,
            {"session_id": session_id}
        ))

    self._temp_highlight_timers[session_id] = asyncio.create_task(clear_after_delay())

def _cancel_temp_highlight_timer(self, session_id: str) -> None:
    """Cancel pending temp highlight timer."""
    timer = self._temp_highlight_timers.pop(session_id, None)
    if timer:
        timer.cancel()
```

### Phase 6: Add Timer Clear Intent

**File: `teleclaude/cli/tui/state.py`**

Add intent type and reducer logic:

```python
class IntentType(str, Enum):
    # ... existing ...
    CLEAR_TEMP_HIGHLIGHT = "clear_temp_highlight"

# In reducer
if t is IntentType.CLEAR_TEMP_HIGHLIGHT:
    session_id = intent.payload["session_id"]
    # Only clear if still temporary (agent hasn't stopped)
    if session_id in state.sessions.temp_output_highlights:
        state.sessions.output_highlights.discard(session_id)
        state.sessions.temp_output_highlights.discard(session_id)
    return state
```

### Phase 7: Remove Inference Logic

**File: `teleclaude/cli/tui/views/sessions.py`**

Remove the `_update_activity_state` method that compares previous vs current state.

Remove the `SESSION_ACTIVITY` intent and related dispatches that infer changes from field comparison.

**File: `teleclaude/cli/tui/state.py`**

Remove `SESSION_ACTIVITY` from `IntentType` enum if no longer used elsewhere.

Remove the `SESSION_ACTIVITY` reducer case.

### Phase 8: State Persistence

**File: `teleclaude/cli/tui/state.py`** (or state_store.py)

Ensure highlight state includes temp tracking:

```python
@dataclass
class SessionViewState:
    input_highlights: set[str] = field(default_factory=set)
    output_highlights: set[str] = field(default_factory=set)
    temp_output_highlights: set[str] = field(default_factory=set)  # Track which are temporary
```

Update save/restore to handle the new field.

## Testing Plan

### Unit Tests

1. **models.py**: Test `SessionUpdateReason` type
2. **cache.py**: Test `notify_session_updated` accepts and stores reason
3. **agent_coordinator.py**: Test correct reason passed for each handler
4. **state.py**: Test reducer handles each reason correctly
5. **Timer logic**: Test 3-second timer start/cancel/expire
6. **CLEAR_TEMP_HIGHLIGHT**: Test only clears if in temp set

### Integration Tests

1. **WebSocket flow**: Verify reason reaches TUI via WebSocket
2. **End-to-end**: Send input → verify reason="user_input" → highlight applied
3. **Timer behavior**: Verify 3-second highlight clears unless agent_stopped received

### Manual Testing

1. Send message in Telegram → verify input highlighted in TUI
2. Wait for agent response → verify highlight transitions
3. Click session → verify output highlight clears
4. Test streaming agents (Gemini) → verify 3-second temp highlights

## Files Changed Summary

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

## Estimated Complexity

- **Reason type**: Low (one type alias)
- **Cache interface**: Low (add parameter)
- **Coordinator changes**: Low (3 call sites)
- **WebSocket payload**: Low (add field)
- **TUI reducer**: Medium (reason-based logic + timer)
- **Remove inference**: Medium (careful deletion)
- **Testing**: Medium (new test cases)

Total: ~300-400 lines of changes across 8 files.

## Why This Approach

1. **Single event stream**: No parallel event bus, no timing coordination
2. **Cache stays simple**: Just passes through what coordinator tells it
3. **Coordinator owns semantics**: The source of "what happened" attaches meaning
4. **Backwards compatible**: `reason=None` works for generic updates
5. **Minimal API change**: One optional parameter added to existing method
