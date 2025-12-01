# AdapterClient Refactor Analysis

## Current Understanding: Correct Architecture Pattern

**AdapterClient is a FACADE/MULTIPLEXER** that broadcasts to ALL UiAdapters.

### Core Principles:
1. **Most methods broadcast to ALL UiAdapters** (Telegram, future Slack, etc.)
2. **Only specific methods go to origin adapter only** (feedback, files)
3. **RedisAdapter excluded from UI broadcasts** (pure transport)
4. **`origin_adapter` field is metadata** - only used for origin-only methods

### Use Cases:
- Telegram user starts session → output in Telegram AND Slack AND all UIs
- AI session via Redis → output in ALL UIs (humans observe AI work)
- Direction doesn't matter → all UIs see all activity

---

## Analysis of Current Code

### ✅ CORRECT IMPLEMENTATIONS (Broadcast to ALL UiAdapters)

**1. `send_message()` (lines 132-196)**
```python
# ✅ Sends to origin adapter (critical)
origin_message_id = await origin_adapter.send_message(...)

# ✅ Then broadcasts to ALL other UiAdapters (observers)
for adapter_type, adapter in self.adapters.items():
    if adapter_type == session.origin_adapter:
        continue  # Skip origin (already sent)
    if isinstance(adapter, UiAdapter):  # ✅ Excludes Redis
        observer_tasks.append(...)
```

**2. `create_channel()` (lines 810-889)**
```python
# ✅ Creates channels in ALL adapters
for adapter_type, adapter in self.adapters.items():
    tasks.append(adapter.create_channel(...))
```

---

### ❌ WRONG IMPLEMENTATIONS (Should Broadcast, Currently Origin-Only)

**1. `edit_message()` (lines 249-278)**
```python
# ❌ WRONG: Only edits in origin adapter
origin_adapter = self.adapters.get(session.origin_adapter)
result = await origin_adapter.edit_message(...)

# ✅ SHOULD BE: Broadcast edit to ALL UiAdapters
# Same pattern as send_message() with origin + observers
```

**2. `delete_message()` (lines 280-308)**
```python
# ❌ WRONG: Only deletes in origin adapter
origin_adapter = self.adapters.get(session.origin_adapter)
result = await origin_adapter.delete_message(...)

# ✅ SHOULD BE: Broadcast delete to ALL UiAdapters
```

**3. `delete_channel()` (lines 484-511)**
```python
# ❌ WRONG: Only deletes in origin adapter
origin_adapter = self.adapters.get(session.origin_adapter)
result = await origin_adapter.delete_channel(...)

# ✅ SHOULD BE: Delete channel in ALL adapters
```

---

### ✅ CORRECT IMPLEMENTATIONS (Origin-Only, Should NOT Broadcast)

**1. `send_feedback()` (lines 198-247)**
```python
# ✅ CORRECT: Only sends to origin adapter
# Ephemeral messages go to requester only
origin_adapter = self.adapters.get(session.origin_adapter)
return await origin_adapter.send_feedback(...)
```

**2. `send_file()` (lines 310-352)**
```python
# ✅ CORRECT: Only sends to origin adapter
# Files delivered to requester only
origin_adapter = self.adapters.get(session.origin_adapter)
result = await origin_adapter.send_file(...)
```

---

## Problems Summary

### 1. **Inconsistent Broadcasting Pattern**
- `send_message()` broadcasts → ✅ CORRECT
- `edit_message()` origin-only → ❌ WRONG (should broadcast)
- `delete_message()` origin-only → ❌ WRONG (should broadcast)
- `delete_channel()` origin-only → ❌ WRONG (should broadcast)

### 2. **Session Lookup Redundancy**
Every method does:
```python
session = await db.get_session(session_id)
if not session:
    raise ValueError(f"Session {session_id} not found")
```

This should be extracted to a helper method.

### 3. **Incorrect Documentation**
`docs/architecture.md` describes origin/observer pattern incorrectly:
- Says: "send to origin, broadcast to observers"
- Reality: "broadcast to ALL UiAdapters (except transport)"

The docs confuse the architecture pattern.

### 4. **Missing Methods**
Not sure if these exist, but based on BaseAdapter interface:
- `update_channel_title()` - should broadcast
- `close_channel()` - should broadcast
- `reopen_channel()` - should broadcast

---

## Recommended Refactoring

### 1. Create Helper Methods

```python
async def _get_session(self, session_id: str) -> Session:
    """Get session or raise ValueError."""
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    if not session.origin_adapter:
        raise ValueError(f"Session {session_id} has no origin adapter")
    return session

async def _broadcast_to_ui_adapters(
    self,
    session: Session,
    operation: str,  # For logging
    origin_task: Callable,
    observer_task: Callable,
) -> Any:
    """Execute operation on origin adapter, then broadcast to observers.

    Args:
        session: Session object
        operation: Operation name for logging
        origin_task: Async callable for origin adapter
        observer_task: Async callable for observer adapters

    Returns:
        Result from origin adapter
    """
    # Send to origin (CRITICAL)
    origin_result = await origin_task()

    # Broadcast to observers (OPTIONAL)
    observer_tasks = []
    for adapter_type, adapter in self.adapters.items():
        if adapter_type == session.origin_adapter:
            continue
        if isinstance(adapter, UiAdapter):
            observer_tasks.append((adapter_type, observer_task(adapter)))

    if observer_tasks:
        results = await asyncio.gather(
            *[task for _, task in observer_tasks],
            return_exceptions=True
        )

        # Log failures (non-critical)
        for (adapter_type, _), result in zip(observer_tasks, results):
            if isinstance(result, Exception):
                logger.warning(
                    "Observer %s failed %s for session %s: %s",
                    adapter_type, operation, session.session_id[:8], result
                )

    return origin_result
```

### 2. Refactor Methods to Use Helper

```python
async def send_message(self, session_id: str, text: str, metadata: MessageMetadata) -> str:
    """Send message to ALL UiAdapters."""
    session = await self._get_session(session_id)
    origin_adapter = self.adapters[session.origin_adapter]

    return await self._broadcast_to_ui_adapters(
        session,
        "send_message",
        lambda: origin_adapter.send_message(session_id, text, metadata),
        lambda adapter: adapter.send_message(session_id, text, metadata),
    )

async def edit_message(self, session_id: str, message_id: str, text: str) -> bool:
    """Edit message in ALL UiAdapters."""
    session = await self._get_session(session_id)
    origin_adapter = self.adapters[session.origin_adapter]

    return await self._broadcast_to_ui_adapters(
        session,
        "edit_message",
        lambda: origin_adapter.edit_message(session_id, message_id, text, MessageMetadata()),
        lambda adapter: adapter.edit_message(session_id, message_id, text, MessageMetadata()),
    )

async def delete_message(self, session_id: str, message_id: str) -> bool:
    """Delete message in ALL UiAdapters."""
    session = await self._get_session(session_id)
    origin_adapter = self.adapters[session.origin_adapter]

    return await self._broadcast_to_ui_adapters(
        session,
        "delete_message",
        lambda: origin_adapter.delete_message(session_id, message_id),
        lambda adapter: adapter.delete_message(session_id, message_id),
    )
```

### 3. Methods That Should Remain Origin-Only

```python
async def send_feedback(self, session_id: str, message: str, metadata: MessageMetadata) -> Optional[str]:
    """Send feedback to origin adapter ONLY (ephemeral)."""
    session = await self._get_session(session_id)
    origin_adapter = self.adapters[session.origin_adapter]
    return await origin_adapter.send_feedback(session_id, message, metadata)

async def send_file(self, session_id: str, file_path: str, caption: Optional[str] = None) -> str:
    """Send file to origin adapter ONLY."""
    session = await self._get_session(session_id)
    origin_adapter = self.adapters[session.origin_adapter]
    return await origin_adapter.send_file(session_id, file_path, MessageMetadata(), caption)
```

---

## Testing Strategy

### Critical Tests to Add:

1. **Multi-adapter broadcasting:**
   - Create session with Telegram as origin
   - Register mock Slack adapter
   - Send message → verify BOTH adapters receive it
   - Edit message → verify BOTH adapters receive edit
   - Delete message → verify BOTH adapters receive delete

2. **Origin-only methods:**
   - Send feedback → verify ONLY origin receives it
   - Send file → verify ONLY origin receives it

3. **Redis exclusion:**
   - Register RedisAdapter
   - Send message → verify Redis does NOT receive broadcast
   - Create channel → verify Redis DOES receive (creates stream)

4. **Observer failure handling:**
   - Mock Slack adapter to fail
   - Send message → verify Telegram still succeeds
   - Verify failure logged as warning, not exception

---

## Migration Plan

1. ✅ Write analysis (this document)
2. Add missing tests for current behavior
3. Implement `_get_session()` helper
4. Implement `_broadcast_to_ui_adapters()` helper
5. Refactor `edit_message()` to broadcast
6. Refactor `delete_message()` to broadcast
7. Refactor `delete_channel()` to broadcast
8. Run tests, fix any issues
9. Update docs/architecture.md with correct pattern
10. Commit with proper tests passing

---

**Next Step:** Get user confirmation on this analysis before proceeding with refactor.

---

## REFACTOR IN PROGRESS

### Completed:
1. ✅ Added `_broadcast_to_observers()` helper
2. ✅ Refactored `send_message()` - broadcasts to ALL UiAdapters + accepts Session
3. ✅ Refactored `send_feedback()` - origin-only + accepts Session
4. ✅ Refactored `edit_message()` - broadcasts to ALL UiAdapters + accepts Session
5. ✅ Refactored `delete_message()` - broadcasts to ALL UiAdapters + accepts Session
6. ✅ Refactored `send_file()` - origin-only + accepts Session

### Key Design Change:
**Methods now accept `Session` object instead of `session_id`**
- Daemon already has session, no need to re-fetch
- Eliminates `_get_session()` helper entirely
- Fail-fast: if session.origin_adapter is None, let it blow up naturally

### TODO:
- [ ] Refactor `delete_channel()` to broadcast
- [ ] Search for other methods needing update
- [ ] Update all daemon/handler callsites
- [ ] Run tests and fix failures
- [ ] Update architecture docs
