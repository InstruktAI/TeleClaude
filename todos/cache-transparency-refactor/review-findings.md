# Review Findings: cache-transparency-refactor

## Round 2

## Verdict: APPROVE

## Summary

Round 2 re-review after merge-conflict resolution. The delivery remains clean and well-scoped. All 8 requirements are traced to implementation. The "always-serve" contract is enforced by API shape (no `include_stale` parameter), callback injection is sound, exception suppression is correct, and deduplication is consistent across all methods. 189 targeted tests pass; 3428 unit tests pass (1 unrelated flaky failure in `test_inbound_queue.py`).

No new Critical or Important findings. All round 1 findings remain resolved.

## Critical

_(none)_

## Important

_(none)_

## Suggestions

### S1. Implementation plan Task 12 unchecked (carried from round 1)

`implementation-plan.md` Task 12 ("Run full test suite and verify bug fix") lacks `[x]`, while the quality checklist reports all tasks checked. Task 12 is a verification task, not a code task, and the build gates confirm tests pass — cosmetic inconsistency.

### S2. `DaemonCache` class docstring could clarify TTL role (carried from round 1)

**Location:** `teleclaude/core/cache.py:63-70`
The class docstring says "Central cache for remote data with TTL management" which implies active TTL filtering. After this refactor, TTL is used only for staleness detection (callback triggering), not filtering. Consider updating to "staleness-aware reads" or similar.

### S3. Add debug log for missing Redis adapter in daemon callback (carried from round 1)

**Location:** `teleclaude/daemon.py:317-319`
The `_on_stale_read` closure silently returns when no Redis adapter is present. Pre-existing pattern. Adding `logger.debug()` when the adapter is absent would make signal drops traceable during debugging.

### S4. Multi-computer stale callback test (carried from round 1)

**Location:** `tests/unit/test_cache.py`
`test_on_stale_read_deduplicates_per_computer` verifies dedup for a single computer with 3 entries. A test with two distinct stale computers (callback fires twice, once per computer) would verify the positive multi-computer path.

### S5. Narrow `get_adapter` type annotation

**Location:** `teleclaude/daemon.py:457`
`get_adapter: Callable[[], object]` could be narrowed to `Callable[[], RedisTransport | None]` to express the actual contract. Low impact since the `isinstance` check handles the runtime behavior.

## Resolved During Review (Round 1)

The following issues were found and auto-remediated during the round 1 review pass:

### R1. Misleading test function name in smoke test

**Location:** `tests/integration/test_e2e_smoke.py:252`
**Was:** `test_stale_cache_data_filtered` — name says "filtered" when behavior is "always served"
**Fixed:** Renamed to `test_stale_cache_data_always_served`

### R2. Missing `get_todo_entries()` callback signaling tests

**Location:** `tests/unit/test_cache.py`
**Was:** `get_todo_entries()` has its own dedup logic separate from `get_projects()`, but no test verified callback invocation or deduplication through this code path.
**Fixed:** Added `test_get_todo_entries_signals_stale_read` and `test_get_todo_entries_deduplicates_callback_per_computer`.

### R3. Stale docstring referencing old API

**Location:** `tests/unit/test_cache.py:351`
**Was:** `"Test get_todo_entries() returns stale entries without needing include_stale."`
**Fixed:** `"Test get_todo_entries() returns stale entries (always-serve contract)."`

### R4. Missing daemon callback wiring tests (Finding 1 from round 1)

**Fix:** Extracted the `_on_stale_read` closure in `TeleClaudeDaemon.__init__` to a
`@staticmethod _make_stale_read_callback(local_computer_name, get_adapter)` factory.
`__init__` now calls the factory; the three behaviors are tested in `test_daemon.py`:

- `test_stale_read_callback_skips_local_computer` — local/named/empty computer → no request
- `test_stale_read_callback_delegates_to_redis_transport` — remote computer + RedisTransport → `request_refresh` called with correct args
- `test_stale_read_callback_skips_when_no_redis_adapter` — adapter is `None` → no error, no refresh

**Commit:** `7eeb86c61`

## Why No Issues (Round 2)

1. **Paradigm-fit:** Cache read methods follow the existing pattern (iterate `_items`, build list, return). Callback injection follows Python convention (optional callable, `None` default). Static factory for testable closure matches the project's test isolation pattern.
2. **Requirements coverage:** All 8 requirements verified — `include_stale` removed (R1-R3), `get_computers()` mutation removed (R4), `is_stale` field/method removed (R5-R6), callback injection wired (R7), callers cleaned up (R8).
3. **Copy-paste duplication:** No duplicated logic introduced. The old `_refresh_stale_projects` and `_refresh_stale_todos` (which were near-duplicates with a bug) are replaced by a single callback path.
4. **Security:** No secrets, no injection vectors, no user-facing error detail leakage. Callback exception suppression is properly scoped with `exc_info=True` logging.

## Positive Observations

- **Copy-paste bug fixed:** The old `_refresh_stale_todos()` was calling `request_refresh(computer, "projects", reason="ttl")` — refreshing projects when todos were stale. The new callback correctly passes `resource_type` through.
- **Clean API surface removal:** No `include_stale`, `DaemonCache.is_stale`, `TodoCacheEntry.is_stale`, or `_refresh_stale_*` references remain anywhere in production or test code.
- **Docstrings updated correctly:** `get_computers()`, `get_projects()`, `get_todos()`, `get_todo_entries()` docstrings accurately reflect the always-serve contract and callback behavior.
- **Daemon callback comment is exemplary:** "Local computers manage freshness via startup warming and TodoWatcher" — concise architectural rationale that prevents future regression.
- **Demo artifact is legitimate:** 5 executable blocks that exercise real code paths, plus manual verification steps.

## Lane Coverage

| Lane | Agent | Result |
|------|-------|--------|
| scope | reviewer direct | Clean — all 8 requirements traced |
| code | next-code-reviewer | Clean — no bugs or pattern violations |
| paradigm | reviewer direct | Clean — follows existing patterns |
| principles | reviewer direct | Clean — no violations introduced |
| security | reviewer direct | Clean |
| tests | next-test-analyzer | Suggestions only (S4, S5 area) |
| errors | next-silent-failure-hunter | Justified suppressions; S3 carried |
| comments | next-comment-analyzer | All resolved in round 1 |
| demo | reviewer direct | Clean — executable and domain-specific |
| docs | reviewer direct | No CLI/config surface changes |
| simplify | — | Not needed (code is already minimal) |
