# Async Improvements - Implementation Plan

## Phase 1: Critical Blocking Fixes (P0)

### Task 1.1: Fix subprocess blocking in next_machine.py

**File:** `teleclaude/core/next_machine.py`

**Changes:**
- Wrap `_prepare_worktree()` subprocess calls in `asyncio.to_thread()`
- Make `ensure_worktree()` async
- Update all callers

**Pattern (from session_cleanup.py:239):**
```python
result = await asyncio.to_thread(_blocking_sync_function)
```

### Task 1.2: Fix psutil blocking in command_handlers.py

**File:** `teleclaude/core/command_handlers.py:491-493`

**Changes:**
- Wrap psutil calls in `asyncio.to_thread()`
- Or use `psutil.cpu_percent(interval=None)` with separate sampling task

## Phase 2: Database Resilience (P1)

### Task 2.1: Add busy timeout to async connection

**File:** `teleclaude/core/db.py:66`

**Add after connect:**
```python
await self._db.execute("PRAGMA busy_timeout = 5000")
```

### Task 2.2: Consider WAL mode

**File:** `teleclaude/core/db.py`

**Add after connect:**
```python
await self._db.execute("PRAGMA journal_mode = WAL")
```

## Phase 3: File I/O (P2)

### Task 3.1: Add aiofiles dependency

**File:** `pyproject.toml`

### Task 3.2: Convert hot path file operations

**Files:** `teleclaude/core/next_machine.py` (18 locations)

Convert `.read_text()` / `.write_text()` to:
```python
import aiofiles
async with aiofiles.open(path, 'r') as f:
    content = await f.read()
```

## Testing

1. Run `make lint` after each phase
2. Run `make test` to verify no regressions
3. Manual verification: Monitor REST responsiveness during worktree operations

## Verification

After all changes:
```bash
make restart && make status
# Verify REST stays responsive during load
```
