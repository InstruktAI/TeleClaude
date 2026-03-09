# cache-transparency-refactor — Input

# Cache Transparency: Remove include_stale and Internalize Refresh

## Context

The TUI preparation pane is empty because _send_initial_state() in api_server.py:2428 calls cache.get_projects() without include_stale=True. After 5 minutes, all projects are stale and filtered out, producing an empty WS preparation_initial event.

The root cause isn't this one missed parameter — it's that include_stale exists at all. The cache contract (project/policy/cache-contract, project/design/architecture/cache) states:

> Always Serve Immediately: return stale if needed.
> TTL Independence: TTL controls refresh cadence, but stale data still served until refresh completes.

Every caller except the buggy one passes include_stale=True, proving the parameter is a footgun that violates the documented architecture.

## What changes

### 1. Remove include_stale from all cache read methods

teleclaude/core/cache.py:
- get_projects(computer, *, include_stale) → get_projects(computer) — remove parameter, remove stale filtering (lines 166-192)
- get_todos(computer, project_path, *, include_stale) → get_todos(computer, project_path) — same (lines 230-248)
- get_todo_entries(*, computer, project_path, include_stale) → get_todo_entries(*, computer, project_path) — same (lines 250-285)

All three methods always return what's cached, regardless of TTL.

### 2. Fix get_computers() — stop deleting stale entries

teleclaude/core/cache.py:150-164

Current code deletes stale computers from the dict on read. Replace with a simple list comprehension that returns everything. Computers are refreshed via heartbeats (push) — the read path should never mutate.

### 3. Remove TodoCacheEntry.is_stale field

teleclaude/core/cache.py:53-60

Remove the is_stale: bool field. This is cache vocabulary leaking into a data transfer object. The dataclass becomes (computer, project_path, todos) only.

### 4. Remove DaemonCache.is_stale() public method

teleclaude/core/cache.py:104-125

Delete entirely. CachedItem.is_stale() stays — it's the internal TTL check mechanism used by the cache's own read methods.

### 5. Add on_stale_read callback injection

teleclaude/core/cache.py — new constructor parameter:

    def __init__(self, on_stale_read: Callable[[str, str], None] | None = None) -> None:

Signature: on_stale_read(resource_type: str, computer: str) where resource_type is 'projects' or 'todos'.

Add private helper _signal_stale_read(resource_type, computer) that calls the callback with exception suppression.

Each read method (get_projects, get_todos, get_todo_entries) calls _signal_stale_read when it encounters a stale entry. The callback is invoked once per stale computer per read, not per item — deduplicate within the method.

### 6. Wire callback in Daemon.__init__

teleclaude/daemon.py:314

    def _on_stale_read(resource_type: str, computer: str) -> None:
        if computer in ('local', config.computer.name, ''):
            return
        adapter = self.client.adapters.get('redis')
        if adapter and hasattr(adapter, 'request_refresh'):
            adapter.request_refresh(computer, resource_type, reason='ttl')

    self.cache = DaemonCache(on_stale_read=_on_stale_read)

Late-bound closure: self.client is captured at construction time, adapter is resolved at call time. Local computers are skipped — TodoWatcher handles local todos, startup handles local projects.

The RedisTransport.request_refresh() already has coalescing, cooldown, and deduplication built in, so rapid stale reads don't spam refresh tasks.

### 7. Clean up all api_server.py callers

teleclaude/api_server.py:

- Line 1622: get_projects(computer_name, include_stale=True) → get_projects(computer_name)
- Lines 1660-1681: Remove stale_computers collection, remove cache.is_stale() call, remove _refresh_stale_projects() call. Just iterate and append.
- Lines 2038-2068: Remove include_stale=True, remove stale_remote_computers collection, remove entry.is_stale reads, remove _refresh_stale_todos() call. Just iterate entries and build DTOs.
- Line 2428: No change needed — get_projects() signature change fixes the bug automatically
- Line 2433: get_todos(..., include_stale=True) → get_todos(...)

Delete dead methods:
- _refresh_stale_projects() (lines 2374-2385)
- _refresh_stale_todos() (lines 2387-2397)

### 8. Update tests

tests/unit/test_cache.py:

- test_get_projects_filters_stale_entries (line 312): Invert: assert stale entries ARE returned. Assert on_stale_read called with ('projects', 'local').
- test_get_projects_includes_stale_when_requested (line 331): Remove — include_stale no longer exists. Replace with test_on_stale_read_called_for_stale_projects.
- test_get_todos_returns_empty_for_stale_data (line 344): Invert: assert stale todos ARE returned. Assert on_stale_read called.
- test_get_todo_entries_include_stale (line 358): Remove include_stale=True arg, remove is_stale field assertion. Assert callback called.
- test_is_stale_returns_true_for_missing_key (line 466): Delete — DaemonCache.is_stale() is removed.
- test_cached_item_is_stale_* (lines 13-45): Keep — these test CachedItem.is_stale() which stays.

New tests:
- test_on_stale_read_not_called_when_fresh — fresh data, no callback invocation
- test_on_stale_read_suppresses_exceptions — callback raises, no propagation
- test_get_computers_returns_stale_entries — verify stale computers returned (not deleted)

tests/unit/test_api_server.py:

- mock_cache fixture (line 67): Remove cache.is_stale = MagicMock(return_value=False)
- test_list_projects_with_cache (line 1238): Update call_args assertion: remove include_stale kwarg
- test_list_todos_all_cached (line 1287): Remove is_stale=False from TodoCacheEntry(), update call_args
- test_list_todos_project_filter (line 1313): Remove is_stale=True from TodoCacheEntry(), update call_args
- test_list_todos_stale_remote_entries_refresh_projects (line 1337): Delete — refresh is now the cache's responsibility, tested in test_cache.py

tests/integration/test_e2e_smoke.py — No changes needed. Line 280 tests CachedItem.is_stale() which stays.

## Execution order

1. cache.py: Remove is_stale from TodoCacheEntry, add on_stale_read + _signal_stale_read, remove DaemonCache.is_stale(), rewrite the four read methods
2. daemon.py: Wire on_stale_read callback
3. api_server.py: Clean all callers, delete dead refresh methods
4. tests/unit/test_cache.py: Update and add tests
5. tests/unit/test_api_server.py: Update tests

## Verification

    python -m pytest tests/unit/test_cache.py tests/unit/test_api_server.py -x -q
    python -m pytest tests/ -x -q

Then manually: open TUI, check preparation pane shows data. Send SIGUSR2 reload, confirm pane still shows data. Wait >5 minutes, reload again, confirm data persists.
