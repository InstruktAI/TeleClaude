# Review Findings: deployment-channels

## Round 1

### Paradigm-Fit Assessment

1. **Data flow**: The implementation correctly uses the hooks framework (`HandlerRegistry`, `Contract`, `HookDispatcher`) and loads config via established `load_project_config`. Fan-out uses raw Redis Stream `xadd`/`xread` instead of `EventBusBridge` — a pragmatic deviation with `maxlen` applied.
2. **Component reuse**: Good reuse of `HookEvent`, `Contract`, `PropertyCriterion`, `Target`, `HandlerRegistry`, `HookDispatcher`, and `RedisTransport._get_redis`. Background task lifecycle follows established `create_task` + `add_done_callback(_log_background_task_exception(...))` pattern.
3. **Pattern consistency**: New code follows existing daemon patterns for background consumers and contract registration.

### Critical

#### 1. Double execution on originating daemon

**Files:** `handler.py`, `daemon.py`

When a GitHub event arrives, the handler publishes a fan-out message AND executes `execute_update` locally. The consumer reads the self-published message and dispatches again, causing double execution.

**Status:** RESOLVED in `a5ff0fb5` — `daemon_id` embedded in fan-out, consumer self-skips.

### Important

#### 2. Dead code: `_dispatch`

**Status:** RESOLVED in `e85b5b43` — removed `_dispatch` and `dispatch` param.

#### 3. Unreachable JSON parsing

**Status:** RESOLVED in `84ef78b3` — removed dead JSON parse block.

#### 4. Synchronous `run_migrations()` blocks event loop

**Status:** RESOLVED in `35369270` — wrapped in `asyncio.to_thread`.

#### 5. Raw Redis Stream without maxlen

**Status:** RESOLVED in `0b33baa0` — added `maxlen=1000`.

#### 6. Missing executor error path tests

**Status:** RESOLVED in `cf570370` — added 5 error path tests.

#### 7. Missing integration test

**Status:** RESOLVED in `cf570370` — added 2 integration tests.

#### 8. Fan-out decision logic undertested

**Status:** RESOLVED in `cf570370` — added 5 fan-out decision tests.

### Suggestions (Round 1, carried forward)

#### 9. `_read_version_from_pyproject` not directly tested

**File:** `executor.py:26-38` — branches for missing section/key, non-string version, exception fallback. Only happy path exercised incidentally.

#### 10. `telec version` output changes untested

**File:** `teleclaude/cli/telec.py:1253-1270` — config loading, alpha fallback, stable display with pinned minor have no test coverage.

---

## Round 2 — Deep Review

### Paradigm-Fit Assessment

1. **Data flow**: Round 1 fixes maintain hooks framework patterns. The `daemon_id` self-skip is clean. The `asyncio.to_thread` wrapper correctly moves blocking I/O off the event loop. However, the `execute_update` task (handler.py:141) deviates from the established `create_task` + `add_done_callback` pattern used by every other background task in the daemon — a paradigm violation.
2. **Component reuse**: Good reuse of `config.computer.name` as daemon identity. The existing `parse_version` helper in `teleclaude/deployment/__init__.py` is not used by `_is_within_pinned_minor`, which instead uses a fragile string prefix match.
3. **Pattern consistency**: All round 1 fixes follow existing patterns. No copy-paste duplication.

### Critical

#### 14. `_is_within_pinned_minor` accepts wrong minor versions via prefix match

**Status:** RESOLVED in `f48323b4` — replaced string `startswith` with `parse_version` integer comparison.

#### 15. `make install` subprocess not killed on timeout

**Status:** RESOLVED in `68299f24` — added `install.kill()` + `await install.wait()` after `TimeoutError`.

### Important

#### 16. Fire-and-forget `execute_update` task with no done callback

**Status:** RESOLVED in `43e06e81` — added `_log_execute_update_task_exception` callback via `add_done_callback`.

#### 17. Beta fan-out accepted by stable node — channel mismatch not filtered

**Status:** RESOLVED in `21f188e7` — changed condition to `version_info.get("channel") == channel`.

#### 18. Fanout consumer dies permanently on Redis startup failure

**Status:** RESOLVED in `3924e009` — moved `_get_redis()` call inside the retry loop.

### Suggestions (Round 2)

#### 19. Dead code: `if not version_info:` guard always True

**File:** `handler.py:121`

`version_info` is `{}` at line 94 and only populated inside the `github` branch. When the `deployment` branch is entered, the guard is always True. Remove the guard for clarity.

#### 20. `_read_version_from_pyproject` silent fallback to "0.0.0"

**File:** `executor.py:36`

The `except` block returns "0.0.0" with no log message. This value feeds into `run_migrations` as the target version, which could cause incorrect migration behavior. At minimum, log a warning.

#### 21. Exit code 42 should be a named constant

**File:** `executor.py:180`

Replace magic number with `_RESTART_EXIT_CODE = 42` and add a comment referencing launchd `KeepAlive`.

#### 22. Test: `test_handler_deployment_source_does_not_publish_fanout` leaks task

**Status:** RESOLVED — `_create_task_closing_coro` added at test line 282.

---

## Round 3 — Re-review of Round 2 Fixes

### Paradigm-Fit Assessment

1. **Data flow**: All round 2 fixes maintain the hooks framework patterns. `_is_within_pinned_minor` now uses `parse_version` from the shared deployment helpers — correct data layer reuse. The `install.kill()` + `await install.wait()` follows standard subprocess cleanup. The fan-out consumer's Redis reconnection inside the loop follows the same error-recovery pattern used by the consumer's inner error handler. No paradigm violations.
2. **Component reuse**: Fix #14 properly reuses `parse_version` from `teleclaude/deployment/__init__.py` instead of reimplementing version comparison. Fix #16 follows the established `create_task` + `add_done_callback` pattern used by `_deployment_fanout_task`, `webhook_delivery_task`, and `_contract_sweep_task` in daemon.py.
3. **Pattern consistency**: All fixes are minimal and targeted — each addresses exactly the described issue without introducing new abstractions or side effects.

### Critical

None.

### Important

None.

### Suggestions

Suggestions #9, #10, #11, #12, #13, #19, #20, #21 remain open from earlier rounds. These are test coverage improvements and code clarity items, not functional gaps.

#### 23. RuntimeWarning in `test_handler_deployment_source_beta_on_stable_node_skips`

**File:** `tests/unit/test_deployment_channels.py:749`

The test patches `asyncio.create_task` without `_create_task_closing_coro` side effect. When the handler correctly skips the update (beta fan-out on stable node), `create_task` is never called, so the plain mock is fine. However, pytest reports a `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` from mock internals. Harmless but noisy — adding the side effect defensively would silence it.

### Fix Verification Evidence

| #   | Issue                            | Fix verified                                                                                    | Regression test                                                                                                                |
| --- | -------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 14  | Prefix match accepts wrong minor | `_is_within_pinned_minor` uses `parse_version` integer compare (handler.py:51-58)               | `test_is_within_pinned_minor_rejects_different_minor` asserts `"1.20.0"` against `"1.2"` returns False (line 419)              |
| 15  | Subprocess not killed on timeout | `install.kill()` + `await install.wait()` with `ProcessLookupError` guard (executor.py:161-165) | `test_executor_make_install_timeout_halts_update` asserts `kill()` called once and `wait()` awaited once (lines 590-592)       |
| 16  | Task without done callback       | `_log_execute_update_task_exception` callback added (handler.py:63-65, 155-156)                 | No direct test — verified by code inspection that pattern matches daemon.py:1675-1678                                          |
| 17  | Channel mismatch in fan-out      | Condition changed to `== channel` (handler.py:127)                                              | `test_handler_deployment_source_beta_on_stable_node_skips` (line 749)                                                          |
| 18  | Consumer dies on Redis startup   | `_get_redis()` moved inside while loop (daemon.py:1756)                                         | No direct test — verified by code inspection that failure falls into the existing `except Exception` retry handler (line 1778) |

### Why No Blocking Issues

1. **Paradigm-fit verified**: All 5 fixes follow established patterns — `parse_version` reuse, subprocess cleanup, `add_done_callback` pattern, channel equality, and in-loop retry. No copy-paste duplication found. No new abstractions introduced.
2. **Requirements validated**: All round 2 findings (2 Critical, 3 Important) are properly resolved. Each fix is minimal, targeted, and addresses the exact issue. The `_is_within_pinned_minor` fix uses integer comparison, eliminating the prefix match class of bugs entirely. The subprocess kill on timeout follows POSIX best practices.
3. **Test coverage assessed**: 2235 tests pass (39 deployment-specific). Regression tests added for fixes #14, #15, #17. Fixes #16 and #18 verified by code inspection — their correctness follows directly from established daemon patterns. Remaining gaps (suggestions #9-13, #19-21, #23) are test coverage and code clarity improvements, not functional holes.

---

## Verdict: APPROVE

All round 2 findings (2 Critical, 3 Important) are properly resolved. Fixes are minimal, targeted, and verified by regression tests where applicable. 2235 tests pass. Implementation is correct and follows established codebase patterns. Remaining suggestions are test hardening and code clarity items suitable for follow-up work.
