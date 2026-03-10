# Demo: cache-transparency-refactor

## Validation

```bash
# 1. Verify include_stale is removed from all cache read signatures
python -c "
import inspect
from teleclaude.core.cache import DaemonCache
for name in ('get_projects', 'get_todos', 'get_todo_entries'):
    sig = inspect.signature(getattr(DaemonCache, name))
    assert 'include_stale' not in sig.parameters, f'{name} still has include_stale'
print('PASS: include_stale removed from all cache read methods')
"
```

```bash
# 2. Verify TodoCacheEntry has exactly 3 fields (no is_stale)
python -c "
from teleclaude.core.cache import TodoCacheEntry
import dataclasses
fields = [f.name for f in dataclasses.fields(TodoCacheEntry)]
assert fields == ['computer', 'project_path', 'todos'], f'Unexpected fields: {fields}'
print('PASS: TodoCacheEntry has correct fields')
"
```

```bash
# 3. Verify DaemonCache.is_stale() is removed
python -c "
from teleclaude.core.cache import DaemonCache
assert not hasattr(DaemonCache, 'is_stale'), 'DaemonCache still has is_stale'
print('PASS: DaemonCache.is_stale() removed')
"
```

```bash
# 4. Verify on_stale_read callback is accepted and invoked for stale reads
python -c "
from datetime import datetime, timedelta, timezone
from teleclaude.core.cache import CachedItem, DaemonCache
from teleclaude.core.models import ProjectInfo

calls = []
def recorder(resource_type, computer):
    calls.append((resource_type, computer))

cache = DaemonCache(on_stale_read=recorder)
stale_ts = datetime.now(timezone.utc) - timedelta(seconds=400)
cache._projects['remote:/p'] = CachedItem(ProjectInfo(name='p', path='/p', description=''), cached_at=stale_ts)

result = cache.get_projects()
assert len(result) == 1, f'Expected 1 project, got {len(result)}'
assert ('projects', 'remote') in calls, f'Callback not invoked: {calls}'
print('PASS: on_stale_read callback works for stale projects')
"
```

```bash
# 5. Run targeted tests
python -m pytest tests/unit/test_cache.py tests/unit/test_api_server.py -x -q
```

## Guided Presentation

### Step 1: The bug that started it all

**Before:** Open the TUI, navigate to the preparation pane, wait 5+ minutes with no activity, then reload. The pane goes empty.

**Why it happened:** `_send_initial_state()` at line 2428 calls `cache.get_projects()` without `include_stale=True`. All projects age past the 5-minute TTL and are filtered out, producing an empty list. The event handler sends an empty preparation state, leaving the user with a blank pane.

**After:** Same steps—wait 5+ minutes, reload TUI. The preparation pane still shows all projects and todos.

**What changed:** `get_projects()` now has no `include_stale` parameter. The signature change makes the existing call at line 2428 correct by default: all reads serve stale data immediately. The daemon callback (new) requests refresh asynchronously in the background.

**Manual verification:**
```bash
# Start the TUI
make dev

# 1. Observe preparation pane is populated
# 2. Click "Reload State" or send SIGUSR2 to the TUI
# 3. Confirm pane still shows data
# 4. Wait 5+ minutes (or hardcode TTL to 5 seconds for faster testing)
# 5. Reload again
# 6. Confirm data persists while "request_refresh" logs appear in the daemon
```

### Step 2: The API surface change

The `include_stale` parameter no longer exists on any cache read method. This means no caller can accidentally opt out of seeing cached data. The cache contract — "always serve immediately" — is now enforced by the API shape itself.

**Code inspection:**
```bash
# Verify signatures
grep -n "def get_projects\|def get_todos\|def get_todo_entries\|def get_computers" teleclaude/core/cache.py
# No `include_stale` parameter anywhere
```

**What to observe:** `get_projects()`, `get_todos()`, `get_todo_entries()` have no `include_stale` parameter. `get_computers()` no longer deletes stale entries from the dict.

### Step 3: The callback mechanism

Instead of callers collecting stale computers and triggering refreshes, the cache itself signals stale reads via an `on_stale_read` callback. The daemon wires this to `RedisTransport.request_refresh()` at construction time.

**Code inspection:**
```bash
# Verify daemon wiring
grep -A 10 "def _on_stale_read" teleclaude/daemon.py
# Callback is defined and passed to DaemonCache()

# Verify refresh methods removed from api_server
grep "_refresh_stale" teleclaude/api_server.py
# No output—methods deleted
```

**What to observe:**
- In daemon startup logs, `DaemonCache initialized` followed by callback wiring (log message or silent success).
- In daemon operation logs, when a remote cache entry ages past TTL and is read, `request_refresh` is called automatically.
- API server code is simpler: no `_refresh_stale_projects()` or `_refresh_stale_todos()` methods exist.

### Step 4: Exception safety

The callback is wrapped in try/except at the cache layer. A broken callback will log an error but never prevent the caller from receiving cached data.

**Code inspection:**
```bash
# Verify exception suppression
grep -A 5 "_signal_stale_read" teleclaude/core/cache.py | grep -E "try|except|logger"
```

**What to observe:** Tests verify exception suppression explicitly. If you break the callback (e.g., make it throw), the read still returns cached data and logs the error.
