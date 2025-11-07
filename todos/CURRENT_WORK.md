# Current Work: Complete Multi-Adapter Architecture

**Status:** 🟡 In Progress
**Priority:** HIGH
**Goal:** Enable AI-to-AI sessions visible in BOTH Redis (for AI) and Telegram (for humans)

---

## Problem Statement

Redis adapter was implemented but **multi-adapter broadcasting is incomplete**:

❌ **Current:** Sessions use ONE adapter (`adapter_type: str`)
✅ **Needed:** Sessions use MULTIPLE adapters (`adapter_types: list[str]`)

**Impact:** AI-to-AI sessions only visible via Redis. Humans cannot observe them in Telegram.

---

## Architecture: AdapterClient as Central Facade

### Design Principle

**AdapterClient owns ALL adapter interactions.** Daemon is adapter-agnostic.

### AdapterClient Responsibilities

1. **Lifecycle Management**
   - Reads `config.yml` (redis.enabled, telegram config)
   - Instantiates adapters based on config
   - Starts/stops all adapters
   - Handles adapter failures gracefully

2. **Session-Aware Broadcasting**
   - `send_message(session_id, text)` → broadcasts to ALL adapters for session
   - Queries session.adapter_types to determine targets
   - Parallel execution with `asyncio.gather()`

3. **Incoming Message Convergence**
   - ALL adapters call same callbacks: `on_command()`, `on_message()`, `on_voice()`
   - AdapterClient aggregates and routes to daemon handlers
   - Deduplication (if message appears in multiple adapters)

4. **Computer Discovery**
   - Manages computer registry (uses Redis if available, falls back to Telegram)
   - Exposes `get_online_computers()`

---

## Implementation Tasks

### Phase 1: Data Model Updates ✅ CRITICAL PATH

**Files:**
- `teleclaude/core/models.py`
- `teleclaude/core/schema.sql`
- `teleclaude/core/session_manager.py`

**Changes:**

```python
# models.py
@dataclass
class Session:
    adapter_types: list[str]  # PLURAL! e.g., ["redis", "telegram"]
    adapter_metadata: dict[str, Any]  # {"redis": {...}, "telegram": {...}}

# schema.sql
CREATE TABLE sessions (
    ...
    adapter_types TEXT NOT NULL DEFAULT '["telegram"]',  -- JSON array
    adapter_metadata TEXT,  -- JSON object
    ...
);

# session_manager.py
async def create_session(
    ...
    adapter_types: list[str],  # Parameter change
    adapter_metadata: dict[str, Any],
    ...
)
```

**Migration:** Add database migration in `SessionManager.initialize()` to convert existing sessions.

---

### Phase 2: AdapterClient Owns Instantiation ✅ CRITICAL PATH

**File:** `teleclaude/core/adapter_client.py`

**Current State:**
```python
# daemon.py (BAD - daemon instantiates adapters)
self.client = AdapterClient(self)
self.telegram_adapter = TelegramAdapter(...)
self.client.adapters["telegram"] = self.telegram_adapter
```

**Target State:**
```python
# daemon.py (GOOD - client instantiates adapters)
self.client = AdapterClient(daemon=self, config=self.config)
await self.client.start()  # Internally creates Telegram, Redis adapters
```

**AdapterClient.__init__() pseudo-code:**
```python
def __init__(self, daemon, config):
    self.daemon = daemon
    self.config = config
    self.adapters: dict[str, BaseAdapter] = {}

    # Instantiate adapters based on config
    if config.get("telegram"):
        self.adapters["telegram"] = TelegramAdapter(config, daemon)

    if config.get("redis", {}).get("enabled", False):
        redis_client = Redis.from_url(...)
        self.adapters["redis"] = RedisAdapter(redis_client, daemon, ...)

    # Register callbacks (ALL adapters call same handlers)
    for adapter in self.adapters.values():
        adapter.on_command(daemon.handle_command)
        adapter.on_message(daemon.handle_message)
        adapter.on_voice(daemon.handle_voice)

async def start(self):
    """Start all adapters."""
    await asyncio.gather(*[a.start() for a in self.adapters.values()])
```

---

### Phase 3: Implement Multi-Adapter Broadcasting ✅ CRITICAL PATH

**File:** `teleclaude/core/adapter_client.py`

**Add method:**
```python
async def send_message(self, session_id: str, text: str, metadata: dict = None):
    """Send to ALL adapters for this session."""
    session = await self.session_manager.get_session(session_id)
    if not session:
        return

    # Get adapters for this session
    tasks = []
    for adapter_type in session.adapter_types:
        adapter = self.adapters.get(adapter_type)
        if adapter:
            tasks.append(adapter.send_message(session_id, text, metadata))

    # Broadcast in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Log failures
    for adapter_type, result in zip(session.adapter_types, results):
        if isinstance(result, Exception):
            logger.error("send_message failed for %s: %s", adapter_type, result)
```

---

### Phase 4: Update Daemon to Use Client ✅ CRITICAL PATH

**Files:**
- `teleclaude/daemon.py`
- `teleclaude/core/polling_coordinator.py`

**Changes:**

```python
# daemon.py - Remove adapter-specific code
class TeleClaudeDaemon:
    def __init__(self, config_path, env_path):
        # ... existing init ...

        # ONLY create client (it creates adapters internally)
        self.client = AdapterClient(daemon=self, config=self.config)

        # REMOVE: self.telegram_adapter = ...
        # REMOVE: self.redis_adapter = ...

    async def start(self):
        await self.client.start()  # Start all adapters

    # REMOVE: _get_adapter_for_session() - AdapterClient handles this

# polling_coordinator.py - Use client directly
async def poll_and_send_output(
    session_id: str,
    adapter_client: AdapterClient,  # Pass client, not adapter
    ...
):
    # ... poll tmux ...

    # Broadcast to ALL adapters
    await adapter_client.send_message(session_id, output_chunk)
```

---

### Phase 5: Update Redis Adapter Session Creation ✅ CRITICAL PATH

**File:** `teleclaude/adapters/redis_adapter.py`

**Change `_create_session_from_redis()`:**
```python
async def _create_session_from_redis(self, session_id: str, data: dict):
    # Create session with BOTH adapters
    await self.session_manager.create_session(
        session_id=session_id,
        computer_name=self.computer_name,
        tmux_session_name=f"{self.computer_name}-ai-{session_id[:8]}",
        adapter_types=["redis", "telegram"],  # Both!
        adapter_metadata={
            "redis": {
                "command_stream": f"commands:{self.computer_name}",
                "output_stream": f"output:{session_id}"
            },
            "telegram": {
                "topic_name": data.get(b"title", b"AI Session").decode("utf-8")
            }
        },
        title=data.get(b"title", b"Unknown Session").decode("utf-8"),
        description=f"AI-to-AI from {data.get(b'initiator', b'unknown').decode('utf-8')}"
    )
```

**CRITICAL:** When Telegram adapter detects new session with its metadata, it should create the topic.

---

### Phase 6: Update Tests

**Files:**
- `tests/unit/test_adapter_client.py` (update existing)
- `tests/unit/test_redis_adapter.py` (update session creation tests)
- `tests/unit/test_session_manager.py` (update for adapter_types)
- `tests/integration/test_multi_adapter_flow.py` (NEW)

**Write tests AFTER code changes pass basic smoke testing.**

---

## Success Criteria

✅ AI-to-AI session created via Redis appears in BOTH:
- Redis streams (for AI consumption via MCP)
- Telegram topic (for human observation)

✅ Output from AI session broadcasts to BOTH adapters in parallel

✅ Humans can type in AI session Telegram topic and interact

✅ All 331+ tests pass

✅ Daemon has zero direct adapter references (all via AdapterClient)

---

## Testing Strategy

### Manual Testing (Before Automated Tests)

1. **Start daemon with both adapters:**
   ```bash
   make restart
   tail -f /var/log/teleclaude.log
   # Should see: "Loaded Telegram adapter" AND "Loaded Redis adapter"
   ```

2. **Send Redis command to create session:**
   ```bash
   redis-cli XADD commands:MozBook * \
     session_id test-123 \
     command "echo 'Hello Telegram'" \
     title "\$remote > \$MozBook - Test" \
     initiator remote
   ```

3. **Verify:**
   - Session created in database with `adapter_types = ["redis", "telegram"]`
   - Telegram topic created (visible in supergroup)
   - Output appears in BOTH Redis stream AND Telegram topic
   - Human can type in Telegram topic and command executes

### Automated Testing (After Manual Smoke Test)

- Update existing tests for `adapter_types: list[str]`
- Add integration test for multi-adapter broadcasting
- Mock AdapterClient in daemon tests

---

## Files to Modify

**Critical Path (Must Change):**
1. ✅ `teleclaude/core/models.py` - adapter_types: list[str]
2. ✅ `teleclaude/core/schema.sql` - JSON array column
3. ✅ `teleclaude/core/session_manager.py` - create_session() signature
4. ✅ `teleclaude/core/adapter_client.py` - owns adapter instantiation + broadcasting
5. ✅ `teleclaude/adapters/redis_adapter.py` - create sessions with both adapters
6. ✅ `teleclaude/daemon.py` - remove direct adapter usage
7. ✅ `teleclaude/core/polling_coordinator.py` - use client.send_message()

**Supporting Changes:**
8. `tests/unit/test_adapter_client.py`
9. `tests/unit/test_redis_adapter.py`
10. `tests/unit/test_session_manager.py`
11. `tests/integration/test_multi_adapter_flow.py` (NEW)

---

## Known Issues / Edge Cases

1. **Telegram adapter needs to detect new sessions and create topics**
   - Currently relies on `/new-session` command
   - Need auto-topic-creation when session has telegram in adapter_types

2. **Graceful degradation if Redis unavailable**
   - AdapterClient should handle Redis connection failures
   - Fall back to Telegram-only mode

3. **Deduplication of incoming messages**
   - If same command comes via both Redis and Telegram, only process once
   - Use session-level locks or message IDs

4. **Computer registry migration**
   - Currently uses Telegram topic polling
   - Spec says use Redis keys with TTL
   - Low priority (current system works)

---

## Out of Scope (Future Work)

- Computer registry migration to Redis heartbeats (low priority)
- Stream cleanup and TTL enforcement
- MCP server full migration to AdapterClient
- WhatsApp/Slack adapter support
- Multi-hop AI communication (Comp1 → Comp2 → Comp3)

---

## Notes

- This refactoring enables the **original design** from `todos/redis_adapter.md`
- Key insight: **AdapterClient is a facade** - daemon should never touch adapters directly
- Benefits: cleaner code, easier testing, true multi-adapter support
- Risk: Medium (database schema change, but we have migration mechanism)

---

## Next Steps

1. Create TODO list with TodoWrite tool
2. Start with Phase 1 (data model updates)
3. Manual smoke test after each phase
4. Write automated tests after all phases complete
5. Commit with proper message

---

**Last Updated:** 2025-11-07
**Author:** Claude Code
**Spec Reference:** `todos/redis_adapter.md` (lines 39-45, 142-361, 767-789)
