# Requirements: cache-transparency-refactor

## Goal

Align cache read methods with the documented cache contract: always serve
immediately, never filter stale data on reads. Move refresh-triggering
responsibility from API callers into the cache layer via a callback, eliminating
the `include_stale` footgun and the bug it caused (empty TUI preparation pane
after TTL expiry).

## In scope

1. **Remove `include_stale` parameter from all cache read methods**
   - `get_projects()`, `get_todos()`, `get_todo_entries()` always return cached
     data regardless of TTL status.
   - Callers no longer decide whether to see stale data — the cache contract
     decides (answer: always yes).
   - Verification: all call sites compile without `include_stale`; no caller
     receives empty results due to TTL filtering.

2. **Stop mutating cache on read in `get_computers()`**
   - Current code deletes stale computer entries from the dict during iteration.
     Replace with a read-only return of all entries.
   - Computer entries are refreshed via heartbeats (push model). The read path
     must not mutate state. [inferred: computers follow the same "always serve"
     invariant as projects/todos]
   - Verification: `get_computers()` returns stale entries; no `pop()` in the
     read path.

3. **Remove `TodoCacheEntry.is_stale` field**
   - This field leaks cache vocabulary into a data transfer object. After
     `include_stale` removal, no consumer needs it.
   - `TodoCacheEntry` becomes `(computer, project_path, todos)` only.
   - Verification: dataclass has three fields; no consumer reads `.is_stale`.

4. **Remove `DaemonCache.is_stale()` public method**
   - The public cache API no longer exposes stale checks to callers.
     [inferred: the current codebase uses `DaemonCache.is_stale()` only from the
     API server stale-refresh path being removed here]
   - `CachedItem.is_stale()` stays — it is the internal TTL mechanism used by
     the cache's own read methods and the new stale-read callback.
   - Verification: `DaemonCache.is_stale` does not exist; `CachedItem.is_stale`
     still works.

5. **Add `on_stale_read` callback injection to `DaemonCache`**
   - `DaemonCache` accepts an optional stale-read callback with signature
     `(resource_type, computer)` where `resource_type` is `"projects"` or
     `"todos"`.
   - When a read returns stale cached data, the cache signals that stale read
     once per stale computer per method call, not once per item.
   - Callback failures are suppressed and logged without changing the read
     result. [inferred: suppressed refresh-trigger failures must remain
     diagnosable]
   - Verification: callback receives correct `(resource_type, computer)` for
     stale reads; exceptions in the callback do not propagate to the caller;
     fresh reads do not invoke the callback.

6. **Wire callback in `Daemon.__init__`**
   - Daemon startup wires the cache callback into the existing remote refresh
     path so stale remote reads request a background refresh without caller
     involvement.
   - Local computers are excluded from that refresh path because local freshness
     is already owned by startup warming and `TodoWatcher`. [inferred]
   - The existing Redis refresh transport remains the refresh mechanism; this
     change does not redefine its contract or coordination behavior.
   - Verification: callback is wired at construction; local computers do not
     trigger refresh; remote stale reads produce refresh requests via the
     existing transport.

7. **Clean up all `api_server.py` callers**
   - Remove `include_stale=True` from all `get_projects`, `get_todos`,
     `get_todo_entries` calls.
   - Remove stale-computer collection logic and `cache.is_stale()` calls.
   - Delete `_refresh_stale_projects()` and `_refresh_stale_todos()` methods —
     refresh responsibility has moved to the cache callback.
   - Preparation-state delivery must no longer depend on a caller remembering an
     opt-in stale flag; the original empty-pane bug is fixed by the cache API
     contract itself.
   - Verification: no `include_stale`, `is_stale`, `_refresh_stale_` references
     remain in `api_server.py` (except `CachedItem.is_stale` if used
     internally).

8. **Update tests**
   - Invert stale-filtering tests: assert stale data IS returned.
   - Add callback tests: `on_stale_read` called for stale, not called for
     fresh, exceptions suppressed.
   - Remove tests for deleted API (`DaemonCache.is_stale`, `include_stale`
     parameter, `TodoCacheEntry.is_stale` field).
   - Update API server test fixtures: remove `cache.is_stale` mock, remove
     `include_stale` from call assertions, remove `is_stale` from
     `TodoCacheEntry` construction.
   - Delete `test_list_todos_stale_remote_entries_refresh_projects` — refresh
     is now the cache's responsibility.
   - Add deterministic coverage for daemon callback wiring so the remote-refresh
     delegation and local-computer skip behavior stay verifiable through tests
     rather than manual inspection. [inferred: `Daemon.__init__` gains new
     behavior that should be pinned by unit tests]
   - Keep `CachedItem.is_stale` tests (unit and smoke) — that API is unchanged.
   - Verification: all tests pass; no test references deleted API surface.

## Out of scope

- Changing `CachedItem.is_stale()` behavior or the TTL values themselves.
- Modifying the `RedisTransport.request_refresh()` contract or its
  coalescing/cooldown logic.
- Session cache changes (sessions use event-driven updates, not TTL).
- Database persistence layer changes.
- Integration/smoke test changes beyond what's needed for the API surface
  removal. [inferred: smoke test at `test_e2e_smoke.py:280` tests
  `CachedItem.is_stale()` which is untouched]

## Success criteria

- [ ] TUI preparation pane shows projects and todos after TTL expiry (the
      original bug).
- [ ] No caller of cache read methods can opt out of receiving stale data.
- [ ] Cache read methods never mutate internal state.
- [ ] Stale reads for remote computers trigger `request_refresh` via the
      callback without caller involvement.
- [ ] Callback exceptions are swallowed and logged — never propagate to API
      handlers.
- [ ] All existing tests pass with updated assertions.
- [ ] New tests cover: callback invoked on stale, not invoked on fresh,
      exception suppression, `get_computers` returns stale entries.

## Verification

- Targeted automated verification:
  `python -m pytest tests/unit/test_cache.py tests/unit/test_api_server.py -x -q`
- Broader regression check:
  `python -m pytest tests/ -x -q`
- Manual observable check: reload the TUI, confirm the preparation pane is
  populated, wait past the five-minute TTL window, reload again, and confirm
  the pane still shows cached projects/todos while refresh happens in the
  background. [inferred: this is the user-visible regression path described in
  `input.md`]

## Constraints

- `CachedItem.is_stale()` must remain — it is the internal TTL primitive.
- `RedisTransport.request_refresh()` signature and behavior are not modified.
- The callback must not introduce async coupling — it is synchronous and
  fire-and-forget.
- The `DaemonCache` constructor must remain backward-compatible: `on_stale_read`
  defaults to `None` so existing non-daemon instantiations (tests) work
  unchanged.

## Risks

- **get_computers mutation removal**: if any caller depends on stale computers
  being auto-expired from the dict, it will now see them. Mitigated: reviewed
  all `get_computers()` callers — they iterate the returned list, not the
  internal dict. [inferred]
- **Callback exception path**: if the callback has a bug that throws on every
  call, the suppression means stale reads silently stop triggering refreshes.
  Mitigated: the callback logs exceptions at error level; existing monitoring
  catches persistent error-level log streams.
