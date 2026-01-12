# Requirements: Per-Computer Interest-Driven Cache

## Problem Statement

The current cache implementation treats interest as a **global boolean** - when any interest in sessions/projects/todos is registered, it pulls data from ALL remote computers. This is architecturally wrong.

### Current (Broken) Behavior

1. User opens TUI → WebSocket connects → `cache.set_interest("sessions")`
2. Redis adapter detects interest → pulls sessions from ALL remote computers
3. REST endpoint called → checks staleness for ALL computers → triggers background pulls for ALL
4. Result: Data pulled for computers user never asked about

### Expected Behavior

1. User opens TUI → WebSocket connects → NO remote data pulled yet
2. User expands "raspi" node in tree → interest registered for raspi ONLY
3. Cache pulls sessions/projects/todos ONLY for raspi
4. "macbook" stays collapsed → NO data pulled for macbook
5. User collapses raspi → interest removed, cache can expire

## Root Cause

Interest tracking is global, not per-computer:

```python
# Current API - global boolean
cache.set_interest("sessions")  # True/False for ALL remotes
cache.has_interest("sessions")  # Returns bool

# Needed API - per-computer
cache.set_interest("sessions", computer="raspi")
cache.has_interest("sessions", computer="raspi")
```

## Requirements

### R1: Per-Computer Interest Registration

The cache must track interest per-computer, not globally.

**API changes:**
```python
# Register interest for specific computer
cache.set_interest(data_type: str, computer: str) -> None

# Check interest for specific computer
cache.has_interest(data_type: str, computer: str) -> bool

# Remove interest for specific computer
cache.remove_interest(data_type: str, computer: str) -> None

# Get all computers with interest in a data type
cache.get_interested_computers(data_type: str) -> list[str]
```

### R2: WebSocket Subscription Per-Computer

When TUI expands a remote computer node, it sends a subscription message specifying which computer.

**Protocol:**
```json
// Current (wrong)
{"subscribe": ["sessions", "projects"]}

// Expected
{"subscribe": {"computer": "raspi", "types": ["sessions", "projects", "todos"]}}
```

### R3: Population Triggers on Interest Registration

When interest is registered for a specific computer, pull that computer's data:

```python
async def on_interest_registered(computer: str, data_types: list[str]):
    if "sessions" in data_types:
        await pull_sessions(computer)
    if "projects" in data_types:
        await pull_projects(computer)
    if "todos" in data_types:
        await pull_todos(computer)
```

### R4: REST Endpoints Are Pure Readers

REST endpoints must NOT trigger any pulls. They read from cache only:

```python
@app.get("/projects")
async def list_projects():
    # Return local projects always
    result = get_local_projects()

    # Add cached remote projects (only for computers with interest)
    for computer in cache.get_interested_computers("projects"):
        result.extend(cache.get_projects(computer))

    return result
```

No staleness checks. No background pulls. Pure read.

### R5: Heartbeats Only Populate Computer List

Heartbeats should update the list of known computers (so TUI can show them in tree), but NOT pull their sessions/projects/todos.

```python
def on_heartbeat(computer_info):
    cache.update_computer(computer_info)  # Updates computer list only
    # Do NOT pull sessions/projects/todos here
```

### R6: Interest Removal on Collapse

When user collapses a remote computer node, interest is removed and cache can be cleared:

```python
// TUI sends
{"unsubscribe": {"computer": "raspi"}}

// Backend handles
cache.remove_interest("sessions", "raspi")
cache.remove_interest("projects", "raspi")
cache.remove_interest("todos", "raspi")
cache.clear_computer_data("raspi")  # Optional: clear immediately or let TTL expire
```

## Files to Modify

| File | Changes |
|------|---------|
| `teleclaude/core/cache.py` | Add per-computer interest tracking API |
| `teleclaude/adapters/rest_adapter.py` | Remove all pull triggers, pure cache reads |
| `teleclaude/adapters/redis_adapter.py` | Trigger pulls only for computers with interest |
| `teleclaude/cli/tui/` | Send per-computer subscribe/unsubscribe on expand/collapse |

## Out of Scope

- TTL-based auto-refresh (Phase 6 of cache-deferreds)
- Manual refresh ('r' key) re-fetch (Phase 5 of cache-deferreds)

These can be added later, but must also respect per-computer interest.

## Testing

1. Open TUI with no remotes expanded → verify NO remote data pulled
2. Expand raspi → verify ONLY raspi data pulled
3. Expand macbook → verify macbook data pulled (raspi already cached)
4. Collapse raspi → verify interest removed
5. REST endpoint called → verify no background pulls triggered
