# Implementation Plan: cache-transparency-refactor

## Overview

Align the cache read API with its documented contract: all reads always serve immediately, never filtering stale data. Move refresh-triggering responsibility from API callers into the cache layer via callback injection.

This fixes the TUI preparation pane bug (empty after TTL expiry) by removing the `include_stale` parameter footgun and baking "always serve" into the cache contract itself.

## Rationale

**Why this approach:**
- The cache contract (project docs) states: "Always serve immediately" and "TTL controls refresh cadence, not availability."
- The `include_stale` parameter violates this contract and is a footgun—all callers except one pass `include_stale=True`, proving the parameter shouldn't exist.
- Moving refresh-trigger responsibility into the cache ensures all readers get consistent behavior without remembering to opt-in.
- Callback injection (vs. direct coupling) lets the cache remain agnostic about refresh mechanisms while deferring the decision to the daemon.

## Tasks

### Task 1: Remove `is_stale` field from `TodoCacheEntry` dataclass
**File:** `teleclaude/core/cache.py:53-60`

**What:**
- Delete the `is_stale: bool` field from the dataclass.
- The dataclass becomes `(computer, project_path, todos)` only.
- No cached state about staleness leaks into the DTO.

**Why:**
- The field exists only to communicate staleness to callers who need to decide whether to trigger refresh. With callback injection, that decision is no longer the caller's responsibility.
- Removing it enforces the new contract: reads return data, never metadata about that data's age.

**Verification:**
- `TodoCacheEntry` has exactly three fields.
- No consumer code reads `.is_stale` off a `TodoCacheEntry`.

---

### Task 2: Add callback injection to `DaemonCache.__init__`
**File:** `teleclaude/core/cache.py:73-101`

**What:**
- Add parameter: `on_stale_read: Callable[[str, str], None] | None = None`
  - Signature: `(resource_type: str, computer: str)` where resource_type is `"projects"` or `"todos"`
- Store as instance variable: `self._on_stale_read = on_stale_read`
- Add private helper method `_signal_stale_read(resource_type: str, computer: str)`:
  - Call `self._on_stale_read(resource_type, computer)` if callback exists
  - Wrap in try-except, log exceptions at error level, swallow (do not propagate)
  - Prevent duplicate signals within a method call by tracking seen computers

**Why:**
- Callback enables the daemon to hook refresh logic without coupling cache to the refresh transport.
- Deduplication (one signal per computer per method call) prevents redundant refresh requests.
- Exception suppression ensures callback bugs don't break reads; logging keeps them diagnosable.
- Default `None` keeps backward compatibility for non-daemon instantiations.

**Verification:**
- `DaemonCache.__init__` accepts `on_stale_read` parameter.
- `_signal_stale_read()` exists and swallows exceptions.
- Fresh reads do not invoke callback.
- Stale reads invoke callback once per unique computer per method call.

---

### Task 3: Rewrite `get_projects()` to always serve cached data
**File:** `teleclaude/core/cache.py:166-192`

**What:**
- Remove `include_stale: bool = False` parameter.
- Remove stale-filtering logic (lines 182-184): `if cached.is_stale(300) and not include_stale: continue`
- All cached projects are returned, regardless of TTL.
- Track stale computers; after the loop, call `_signal_stale_read("projects", comp_name)` once per unique stale computer.
- Signature becomes: `def get_projects(self, computer: str | None = None) -> list[ProjectInfo]:`

**Why:**
- Removes the footgun parameter; all reads are consistent.
- Callback signals stale data to the daemon; the daemon decides to refresh asynchronously.
- Caller gets immediate response with cached data (no empty result after TTL).

**Verification:**
- All projects in `_projects` dict are returned (regardless of TTL status).
- `is_stale` check still runs internally to determine when to signal callback.
- Callback invoked for each stale computer once per method call.
- No `include_stale` parameter remains.

---

### Task 4: Rewrite `get_todos()` to always serve cached data
**File:** `teleclaude/core/cache.py:230-248`

**What:**
- Remove `include_stale: bool = False` parameter.
- Remove stale-filtering logic (lines 245-246).
- Always return `cached.data` if it exists, regardless of TTL.
- Signal stale read if `cached.is_stale(300)`.
- Signature becomes: `def get_todos(self, computer: str, project_path: str) -> list[TodoInfo]:`

**Why:**
- Identical rationale to `get_projects()`.
- Simple binary behavior: has cached data → return it; no cached data → empty list.

**Verification:**
- If cache key exists, data is returned (even if stale).
- Callback signaled if entry is stale.
- Signature matches updated consumers.

---

### Task 5: Rewrite `get_todo_entries()` to always serve cached data
**File:** `teleclaude/core/cache.py:250-285`

**What:**
- Remove `include_stale: bool = False` parameter.
- Remove stale-filtering logic (lines 275-276).
- Return all entries regardless of TTL.
- Build `TodoCacheEntry` with only three fields (remove `.is_stale=is_stale` kwarg).
- Track stale computers and signal via `_signal_stale_read("todos", comp_name)` once per unique computer.
- Signature becomes: `def get_todo_entries(self, *, computer: str | None = None, project_path: str | None = None) -> list[TodoCacheEntry]:`

**Why:**
- Removes `include_stale` parameter and `is_stale` field usage.
- Keeps deduplication logic for callback signals.
- Consistent with other read methods.

**Verification:**
- All matching entries returned, regardless of TTL.
- `TodoCacheEntry` constructed with three args (no `is_stale`).
- Callback signaled per unique stale computer.

---

### Task 6: Rewrite `get_computers()` to return all cached entries (no mutation)
**File:** `teleclaude/core/cache.py:150-164`

**What:**
- Remove the `pop()` call that deletes stale computers from the dict.
- Replace the mutation loop with a simple list comprehension or loop that returns all entries.
- Remove the "auto-expire" behavior; stale computers are returned as-is.
- Optionally signal stale reads if a callback is wired (not strictly required per requirements, but consistent with other methods).
- Docstring: update to reflect "returns all cached computers, including stale ones".

**Why:**
- The cache contract is "always serve immediately"; reads must not mutate state.
- Computers are refreshed via heartbeats (push model), not on-demand via polling; the read path has no business deleting them.
- Stale computer entries remain in the cache until explicitly invalidated or refreshed.

**Verification:**
- No `pop()` in the read path.
- All computers in `_computers` dict are returned.
- Method does not delete or mutate internal state.

---

### Task 7: Remove `DaemonCache.is_stale()` public method
**File:** `teleclaude/core/cache.py:104-125`

**What:**
- Delete the entire method.
- `CachedItem.is_stale()` (the internal TTL check) remains untouched.

**Why:**
- Public cache API no longer exposes stale-check to callers; reads handle staleness internally.
- The old API was only used by callers deciding whether to refresh—that responsibility has moved to the cache.

**Verification:**
- `DaemonCache.is_stale` method does not exist.
- `CachedItem.is_stale()` still exists and works.
- No compile errors in callers.

---

### Task 8: Wire callback in `Daemon.__init__`
**File:** `teleclaude/daemon.py:314`

**What:**
- Define a private method or closure `_on_stale_read(resource_type: str, computer: str)`:
  ```python
  def _on_stale_read(resource_type: str, computer: str) -> None:
      # Skip local computers; they don't use the refresh transport
      if computer in ('local', config.computer.name, ''):
          return
      # Resolve adapter at call time; don't cache it
      adapter = self.client.adapters.get('redis')
      if adapter and hasattr(adapter, 'request_refresh'):
          adapter.request_refresh(computer, resource_type, reason='ttl')
  ```
- Update cache initialization: `self.cache = DaemonCache(on_stale_read=_on_stale_read)`
- Late-bind the closure so `self.client` is captured at construction time but adapter is resolved on each callback.

**Why:**
- Wires refresh trigger into the cache without coupling cache to daemon internals.
- Local-computer skip prevents redundant refresh requests (local data is owned by TodoWatcher and startup warming).
- Fire-and-forget callback is safe; RedisTransport has its own coalescing and cooldown.

**Verification:**
- Callback is passed to `DaemonCache` constructor.
- Local computers are skipped (no refresh request sent).
- Remote stale reads produce `request_refresh` calls via the existing transport.
- No type errors or adapter lookup failures logged during normal operation.

---

### Task 9: Clean up `api_server.py` — Remove `include_stale` and stale-collection logic
**File:** `teleclaude/api_server.py` (multiple locations)

**What:**

**Line 1622:** `self.cache.get_projects(computer_name, include_stale=True)` → `self.cache.get_projects(computer_name)`

**Lines 1660-1681:**
- Remove `stale_computers: set[str] = set()` variable.
- Remove the `cache.is_stale(cache_key, 300)` call.
- Remove `stale_computers.add(comp_name)`.
- Remove the `self._refresh_stale_projects(stale_computers)` call at line 1681.
- Keep the loop that appends projects to result; no callback needed here (cache handles it).

**Lines 2038-2068:**
- Remove `include_stale=True` from `get_todo_entries()` call(s).
- Remove code that reads `entry.is_stale` (it no longer exists).
- Remove stale-computer collection logic.
- Remove `self._refresh_stale_todos()` call.
- Keep the loop that builds TodoDTO objects.

**Line 2428:** No change needed (signature change fixes the bug automatically).

**Line 2433:** `self.cache.get_todos(..., include_stale=True)` → `self.cache.get_todos(...)`

**Delete methods:**
- `_refresh_stale_projects()` (lines 2374-2385)
- `_refresh_stale_todos()` (lines 2387-2397)

**Why:**
- Removes all footgun parameters and associated stale-collection logic.
- Cache now handles refresh triggering; callers just read.
- Fixes the original bug: `_send_initial_state()` at line 2428 already calls `get_projects()` without `include_stale=True`, which was the bug. Signature change makes it work correctly.

**Verification:**
- No `include_stale=True` or `include_stale=False` references remain in the file.
- No `cache.is_stale()` calls remain.
- No `_refresh_stale_*` method definitions or calls remain.
- API server code is simplified; no refresh logic in the endpoints.

---

### Task 10: Update `tests/unit/test_cache.py` — Invert stale-filtering tests and add callback tests
**File:** `tests/unit/test_cache.py`

**What:**

**Invert existing tests:**
- `test_get_projects_filters_stale_entries` (line 312): Assert stale projects ARE returned. Assert `on_stale_read` called with `("projects", "local")`.
- `test_get_todos_returns_empty_for_stale_data` (line 344): Assert stale todos ARE returned (not empty). Assert callback called.
- `test_get_todo_entries_include_stale` (line 358): Remove `include_stale=True` argument. Remove `is_stale=True` field assertion. Assert callback called.

**Delete tests (for deleted API):**
- `test_is_stale_returns_true_for_missing_key` (line 466): `DaemonCache.is_stale()` no longer exists.
- `test_get_projects_includes_stale_when_requested` (line 331): `include_stale` parameter no longer exists.

**Keep tests (unchanged API):**
- `test_cached_item_is_stale_with_zero_ttl` through `test_cached_item_is_stale_at_boundary`: These test `CachedItem.is_stale()`, which is internal and unchanged.

**Add new tests:**
- `test_on_stale_read_not_called_when_fresh`: Fresh data, callback not invoked.
- `test_on_stale_read_called_for_stale_projects`: Stale data, callback invoked with `("projects", computer)`.
- `test_on_stale_read_called_for_stale_todos`: Stale data, callback invoked with `("todos", computer)`.
- `test_on_stale_read_suppresses_exceptions`: Callback raises, exception is swallowed, read result unaffected, error logged.
- `test_on_stale_read_deduplicates_per_computer`: Multiple stale entries from same computer, callback invoked once per method call.
- `test_get_computers_returns_stale_entries`: Stale computers are returned (not deleted).

**Why:**
- Inverted tests enforce the new "always serve" contract.
- Callback tests verify the new mechanism works correctly.
- Deleted API tests reflect removed surface.
- Kept `CachedItem` tests ensure the internal TTL mechanism stays stable.

**Verification:**
- All tests pass.
- No test references `include_stale` or `DaemonCache.is_stale()`.
- No test constructs `TodoCacheEntry` with `is_stale=` kwarg.
- Callback behavior fully tested (invoke, deduplicate, suppress exceptions).

---

### Task 11: Update `tests/unit/test_api_server.py` — Remove deleted API references
**File:** `tests/unit/test_api_server.py`

**What:**

**Update fixtures:**
- `mock_cache` fixture (line 67): Remove `cache.is_stale = MagicMock(return_value=False)`.

**Update test assertions:**
- `test_list_projects_with_cache` (line 1238): Update `call_args` assertion; remove `include_stale` kwarg from expected call.
- `test_list_todos_all_cached` (line 1287): Remove `is_stale=False` from `TodoCacheEntry()` constructor.
- `test_list_todos_project_filter` (line 1313): Remove `is_stale=True` from `TodoCacheEntry()` constructor.

**Delete tests (for deleted responsibility):**
- `test_list_todos_stale_remote_entries_refresh_projects` (line 1337): API server no longer collects stale entries; refresh is cache's responsibility (tested in `test_cache.py`).

**Why:**
- API server tests reflect the new simpler API.
- Refresh-responsibility tests move to cache tests (proper separation).
- Deleted DTO field usage is removed.

**Verification:**
- No `include_stale` in mock setup or call assertions.
- No `is_stale` in `TodoCacheEntry` construction.
- All API server tests pass.
- Deleted test reflected in other cache-focused test coverage.

---

### Task 12: Run full test suite and verify bug fix
**What:**
- Run targeted suite: `python -m pytest tests/unit/test_cache.py tests/unit/test_api_server.py -x -q`
- Run full suite: `python -m pytest tests/ -x -q`
- Manual check (TUI reload):
  1. Start TUI.
  2. Observe preparation pane populated with projects/todos.
  3. Send `SIGUSR2` to TUI to reload.
  4. Confirm pane still shows data.
  5. Wait past the 5-minute TTL.
  6. Send `SIGUSR2` again.
  7. Confirm pane shows cached data while refresh happens in background.

**Why:**
- Verifies all code changes compile and don't break existing behavior.
- Manual check confirms the original bug is fixed: TUI doesn't show an empty pane after TTL.
- Full suite catch regressions in integration and smoke tests.

**Verification:**
- All tests pass.
- TUI preparation pane remains populated after TTL expiry.
- No refresh requests are duplicated (transport's coalescing works).

---

## Execution Order

1. **Task 1**: Remove `is_stale` field (removes DTO bloat).
2. **Task 2**: Add callback injection (new mechanism).
3. **Task 3-6**: Rewrite read methods (implement contract change, call callback).
4. **Task 7**: Remove public `is_stale()` (clean API).
5. **Task 8**: Wire callback (activate mechanism).
6. **Task 9**: Clean up callers (remove footgun usage).
7. **Task 10-11**: Update tests (verify new behavior).
8. **Task 12**: Full verification (end-to-end proof).

**Rationale for order:**
- Core cache changes first (Tasks 1-7), ensuring the new mechanism is self-contained.
- Daemon wiring (Task 8) activates the mechanism; error-safe because callback is optional.
- Caller cleanup (Task 9) applies the new API; safe because reads remain backward-compatible (just fewer parameters).
- Tests (Tasks 10-11) verify the contract change.
- Full verification (Task 12) catches any integration issues.

## Review Anticipation

**Changes are review-proof because:**
- The requirements are approved and detailed.
- The callback mechanism is callback-safe: exceptions suppressed, logging in place.
- Backward compatibility maintained: callback defaults to `None`, existing tests still run.
- Integration is safe: cache reads remain non-breaking, they just don't filter anymore.
- The bug fix is direct: removing the footgun parameter on one call site (line 2428) fixes the original empty-pane issue.
- All mutation removed: `get_computers()` no longer deletes; read methods no longer filter.
- All test changes follow the inversion pattern: stale data IS returned, callback IS called.

**Potential findings and mitigations:**
- **Finding: Callback overhead.** Mitigation: Callback is fire-and-forget, no await, exceptions suppressed; overhead is minimal. Transport already has coalescing.
- **Finding: Stale computers in list.** Mitigation: By design; computers are refreshed via push (heartbeats), not polling. Returning stale entries is correct until explicit invalidation.
- **Finding: Missing logging.** Mitigation: Task 2 includes error logging in callback exception path; transport logs refresh requests.

---

## Risks & Mitigation

| Risk | Mitigation |
|------|-----------|
| Callback exception masks bugs | Logged at error level; monitoring catches persistent error streams |
| Stale data shown to users | By design; background refresh follows via callback; no user-visible change |
| Refresh requests duplicated | RedisTransport has coalescing & cooldown built in; tested |
| Tests miss new callback behavior | Task 10 adds dedicated callback tests covering invoke, deduplicate, suppress |
| API callers still pass `include_stale` | Signature change prevents accidental use; old code won't compile |
| Stale computer entries bloat memory | Heartbeats keep them fresh; explicit invalidation still possible; low risk in practice |

---

## Success Criteria

- ✓ All requirements from `requirements.md` implemented.
- ✓ TUI preparation pane shows projects/todos after TTL expiry (original bug fixed).
- ✓ No `include_stale` parameter in public cache API.
- ✓ No `DaemonCache.is_stale()` public method.
- ✓ No `TodoCacheEntry.is_stale` field.
- ✓ Cache reads never filter data based on TTL.
- ✓ Stale reads trigger callback (once per computer per method call).
- ✓ Callback exceptions suppressed and logged.
- ✓ All tests pass (unit, functional, smoke).
- ✓ No breaking changes to non-cache API surface.
