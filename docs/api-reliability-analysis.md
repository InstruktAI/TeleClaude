# API Server Reliability Analysis

## Executive Summary

The API server experiences intermittent unavailability due to **blocking operations in async code paths**. The fundamental issue is that Python's asyncio event loop is being blocked by synchronous operations, causing the entire server to become unresponsive.

## Critical Findings

### 1. Blocking Subprocess Calls in Async Functions

**Location:** `teleclaude/core/next_machine.py:989-1061`

**Problem:** The `_prepare_worktree()` function uses synchronous `subprocess.run()` which is called from the async `next_work()` function WITHOUT using `asyncio.to_thread()`.

```python
# BLOCKING - blocks entire event loop
subprocess.run(
    ["make", "worktree-prepare", f"SLUG={slug}"],
    cwd=cwd,
    check=True,
    capture_output=True,
    text=True,
)
```

**Impact:** When preparing a worktree, the entire event loop freezes for the duration of the subprocess (potentially several seconds for `make` or `npm` commands).

**Fix Pattern:** Use `asyncio.to_thread()` as done correctly in `session_cleanup.py:239`:
```python
result = await asyncio.to_thread(_blocking_function)
```

### 2. Blocking psutil Calls in API Endpoints

**Location:** `teleclaude/core/command_handlers.py:493`

**Problem:** `psutil.cpu_percent(interval=0.1)` blocks for 100ms to measure CPU. Called from async `handle_get_computer_info()`.

```python
async def handle_get_computer_info() -> ComputerInfo:
    # ...
    cpu_percent = psutil.cpu_percent(interval=0.1)  # BLOCKS 100ms!
```

**Impact:** Every call to `/computers` endpoint blocks the event loop for 100ms.

**Fix:** Use `asyncio.to_thread()` or use non-blocking `psutil.cpu_percent(interval=None)` with cached values.

### 3. Synchronous File I/O in Async Functions

**Location:** `teleclaude/core/next_machine.py` (multiple locations)

**Problem:** Extensive use of `.read_text()` and `.write_text()` which are synchronous:
- Line 237, 245, 275, 320, 330, 448, 500, 514, 552, 580, 589, 622, 653, 690, 782, 819, 1308, 1388

**Impact:** Each file read/write blocks the event loop. Small files are fast, but under load this adds up.

**Fix:** Use `aiofiles` for async file I/O:
```python
import aiofiles
async with aiofiles.open(path, 'r') as f:
    content = await f.read()
```

### 4. Missing Database Busy Timeout

**Location:** `teleclaude/core/db.py:66`

**Problem:** The async database connection doesn't set `busy_timeout`:
```python
self._db = await aiosqlite.connect(self.db_path)
# Missing: await self._db.execute("PRAGMA busy_timeout = 5000")
```

**Impact:** When concurrent database access occurs (e.g., sync lookup from hooks + async operations from daemon), SQLite fails immediately instead of waiting.

**Fix:** Set a reasonable busy timeout after connection:
```python
self._db = await aiosqlite.connect(self.db_path)
await self._db.execute("PRAGMA busy_timeout = 5000")  # 5 second timeout
```

### 5. Competing Database Connections

**Location:** `teleclaude/core/db.py:1063-1090`

**Problem:** Sync helper functions (`get_session_id_by_field_sync`, `get_session_id_by_tmux_name_sync`) create their own SQLite connections that compete with the main async connection.

**Impact:** Can cause lock contention when hooks (which run sync) query the database while the daemon is writing.

**Fix:** Either:
1. Make hook receiver async and use the daemon's connection
2. Use WAL mode for SQLite (allows concurrent readers)

## Remediation Priority

### P0 - Immediate (Blocking the Event Loop)

1. **Wrap subprocess calls in `asyncio.to_thread()`** in `next_machine.py`
2. **Fix psutil blocking** - use cached values or thread pool

### P1 - High (Database Reliability)

3. **Add busy_timeout to async database connection**
4. **Consider SQLite WAL mode** for better concurrency

### P2 - Medium (Performance Under Load)

5. **Use aiofiles for file I/O** in hot paths
6. **Consolidate sync database helpers** to reduce connection churn

## Verification Steps

After fixes, verify with:

```bash
# Monitor event loop blocking
python -c "
import asyncio
import time

def check_blocking():
    start = time.monotonic()
    asyncio.get_event_loop().call_later(0, lambda: print(f'Loop was blocked for {(time.monotonic()-start)*1000:.0f}ms'))
"

# Run under load
ab -n 100 -c 10 http+unix:///tmp/teleclaude-api.sock/health
```

## Related Files

- `teleclaude/api_server.py` - API server implementation
- `teleclaude/core/command_handlers.py` - Command handlers called by API
- `teleclaude/core/next_machine.py` - Work orchestration with subprocess calls
- `teleclaude/core/db.py` - Database operations
- `teleclaude/core/session_cleanup.py` - GOOD EXAMPLE of proper async subprocess usage
