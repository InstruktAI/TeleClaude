# Implementation Plan: startup-cache-hook-fixes

## Overview

Two bug fixes with minimal code changes. No architectural changes required.

---

## Bug 1: Hook Agent Propagation

### Task 1.1: [x] Add agent_name to hook payload

**File:** `teleclaude/hooks/receiver.py`

**Location:** Line ~433, before `_enqueue_hook_event()` call

**Change:**
```python
# Add agent name to payload before enqueuing
data["agent_name"] = args.agent
_enqueue_hook_event(teleclaude_session_id, event_type, data)
```

### Task 1.2: [x] Handle missing active_agent in daemon

**File:** `teleclaude/daemon.py`

**Location:** `_process_agent_stop()` method, around line 920

**Change:** Replace the hard error with graceful handling:
```python
session = await db.get_session(session_id)
if not session:
    raise ValueError(f"Session {session_id[:8]} not found")

# If active_agent missing, extract from hook payload and update session
if not session.active_agent:
    agent_name = payload.raw.get("agent_name")
    if agent_name:
        logger.info("Session %s missing active_agent, setting from hook payload: %s", session_id[:8], agent_name)
        await db.update_session(session_id, active_agent=agent_name)
        session = await db.get_session(session_id)  # Refresh
    else:
        logger.warning("Session %s missing active_agent, no agent in payload - skipping", session_id[:8])
        return
```

---

## Bug 2: Initial Cache Population

### Task 2.1: [ ] Add cache population method

**File:** `teleclaude/adapters/redis_adapter.py`

**Location:** New method after `_ensure_connection_and_start_tasks()`

**Change:**
```python
async def _populate_initial_cache(self) -> None:
    """Populate cache with remote computers and projects on startup.

    Ensures every daemon has remote computers + projects in cache immediately.
    Uses discover_peers() which queries heartbeat keys (active scan, not waiting).
    """
    if not self.cache:
        logger.debug("Cache unavailable, skipping initial cache population")
        return

    logger.info("Populating initial cache from remote computers...")

    # 1. Discover peers (active query of heartbeat keys)
    peers = await self.discover_peers()

    # 2. Populate computer cache
    for peer in peers:
        self.cache.update_computer({
            "name": peer.name,
            "status": "online",
            "last_seen": peer.last_seen,
            "adapter_type": peer.adapter_type,
            "user": peer.user,
            "host": peer.host,
            "role": peer.role,
            "system_stats": peer.system_stats,
        })

    # 3. Pull projects for each computer
    for peer in peers:
        try:
            await self.pull_remote_projects(peer.name)
        except Exception as e:
            logger.warning("Failed to pull projects from %s: %s", peer.name, e)

    logger.info("Initial cache populated: %d computers", len(peers))
```

### Task 2.2: [ ] Call cache population on startup

**File:** `teleclaude/adapters/redis_adapter.py`

**Location:** `_ensure_connection_and_start_tasks()` method, after `_connect_with_backoff()`

**Change:**
```python
async def _ensure_connection_and_start_tasks(self) -> None:
    """Connect and launch background tasks with retry, without blocking daemon startup."""

    await self._connect_with_backoff()

    if not self._running:
        return

    # NEW: Populate initial cache from existing heartbeats + projects
    await self._populate_initial_cache()

    # Start background tasks once connected
    # ... existing code ...
```

---

## Testing

### Unit Tests

- [ ] Test receiver adds agent_name to payload
- [ ] Test daemon handles NULL active_agent with payload agent
- [ ] Test daemon handles NULL active_agent without payload agent (skip gracefully)
- [ ] Test `_populate_initial_cache()` calls discover_peers and pull_remote_projects

### Integration Tests

- [ ] Manual: Create session via Telegram, start claude manually, verify summary works
- [ ] Manual: Start fresh daemon, verify `teleclaude__list_computers` shows remotes

---

## Risks

- **discover_peers() timeout**: If remote computers are slow to respond, startup could be delayed. Mitigated by existing 3s timeout per computer in discover_peers().
- **Empty heartbeat keys**: If no other computers are online, cache stays empty (expected behavior).
