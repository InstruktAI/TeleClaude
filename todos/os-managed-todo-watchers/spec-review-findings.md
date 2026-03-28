# spec-review-findings — os-managed-todo-watchers

**Verdict: approve**
**Round: 2**

---

## Round 1 (needs_work)

### F1 — No test specifications exist (Critical) — RESOLVED

All requirements now have xfail-marked test specifications across 5 files.

---

## Round 2 (approve)

All requirements R1-R6 have behavioral test coverage. 102 xfail-marked tests
committed and verified green. No Critical or Important findings remain.

### Observations (non-blocking, for builder awareness)

**O1 — Route test mock helpers prescribe internal function names**

The mock targets in `test_todo_watcher_route.py` (`_get_watcher_secret`,
`_recompute_todos`, `_invalidate_stale_preparations`, etc.) prescribe a
specific internal decomposition. The behavioral assertions are sound — the
builder may need to adjust mock target paths to match actual implementation
without weakening the assertions.

**O2 — Installation helpers read real filesystem paths**

`_find_plist_content` and `_find_systemd_service_content` read from
`~/Library/LaunchAgents` and `~/.config/systemd/user`. With `subprocess.run`
mocked, no files will be written. The builder should restructure these helpers
to use the installer's output path or mock the filesystem, preserving the
behavioral assertions (plist contains KeepAlive, service has Restart=, etc.).

**O3 — Async batching tests use hardcoded sleep**

`asyncio.sleep(2.0)` in `test_todo_watcher_process.py` assumes a debounce
window. The builder should either configure the debounce window to a known
test value or increase the sleep margin. The behavioral contracts (coalesce
within window, separate batches after window) are correct.

### Coverage Summary

| Requirement Group              | File                           | Strength                                                  |
| ------------------------------ | ------------------------------ | --------------------------------------------------------- |
| R1.2-R1.5 (filter)             | `test_todo_watcher_filter.py`  | Strong — parametrized accept/reject with boundary cases   |
| R1.1, R1.6-R1.7 (process)      | `test_todo_watcher_process.py` | Good — batching, dedup, no semantic processing            |
| R2.1-R2.7, R6.1 (route)        | `test_todo_watcher_route.py`   | Strong — auth, trust, re-filtering, digest-gated emission |
| R3.1-R3.4, R4.1-R4.6 (install) | `test_todo_watcher_install.py` | Good — secret mgmt, platform services, idempotent         |
| R5.1-R5.2 (removal)            | `test_todo_watcher_removal.py` | Strong — AST-based verification of code removal           |
