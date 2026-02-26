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

## Round 2 — Re-review of Fixes

### Paradigm-Fit Assessment

1. **Data flow**: All fixes maintain the established hooks framework patterns. The `daemon_id` self-skip is implemented at the consumer level (daemon.py), keeping handler logic clean. The `asyncio.to_thread` wrapper correctly moves blocking I/O off the event loop. No paradigm violations introduced.
2. **Component reuse**: The fix reuses `config.computer.name` as daemon identity — consistent with how the rest of the codebase identifies the local daemon (executor.py status keys, transport, lifecycle).
3. **Pattern consistency**: The consumer docstring clearly explains the self-skip rationale. Code follows existing patterns.

### Critical

None.

### Important

None.

### Suggestions

#### 11. Consumer-side `daemon_id` self-skip has no direct test coverage

**File:** `daemon.py:1773-1777`

The daemon_id self-skip guard — the core mechanism preventing double execution (Critical #1 fix) — lives in `_deployment_fanout_consumer`. No test exercises this code path. The handler-level fan-out tests cover decision logic, but the consumer's `if event.properties.get("daemon_id") == config.computer.name: continue` is untested. A regression removing or misconfiguring this check would not be caught.

Testing the consumer requires mocking the Redis streaming loop, which is non-trivial. Acceptable to defer, but worth noting the coverage gap.

#### 12. Fan-out publication test does not verify `daemon_id` payload

**File:** `tests/unit/test_deployment_channels.py:244-265`

`test_handler_github_source_publishes_fanout` asserts `mock_redis.xadd.assert_awaited_once()` but does not inspect the event payload to confirm `daemon_id` is present. Verifying the call args would close the contract between publisher (handler) and consumer (daemon).

#### 13. No test pins `asyncio.to_thread` as the execution mechanism for `run_migrations`

**File:** `tests/unit/test_deployment_channels.py` (executor tests)

All executor tests patch `run_migrations` directly. The mock is correctly called through `asyncio.to_thread`, but if the `to_thread` wrapper were reverted to a direct call, all tests would still pass. One test asserting `asyncio.to_thread` was called with `run_migrations` would pin this contract.

### Why No Blocking Issues

1. **Paradigm-fit verified**: All changes follow established hooks framework, config access, and daemon patterns. No copy-paste duplication found. The `daemon_id` approach reuses the existing `config.computer.name` identity.
2. **Requirements validated**: All 8 round 1 findings are properly resolved. Each fix is targeted, minimal, and addresses the exact issue described. The critical double-execution bug fix is architecturally sound — the consumer self-skip via `daemon_id` is race-free (the `xadd` completes before the consumer's `xread` returns, and the comparison is a simple string equality against immutable config).
3. **Test coverage assessed**: 33 tests pass covering config validation, handler decision logic per channel, executor happy and error paths, fan-out publish/no-publish, integration wire-up, and fan-out decision logic for deployment-source events. Remaining gaps (suggestions #11-13) are test hardening, not functional holes.

---

## Verdict: APPROVE

All round 1 findings (1 Critical, 7 Important) are properly resolved. Implementation is correct, fixes are minimal and targeted, and test coverage is substantially improved (33 tests). Remaining suggestions (#9-13) are test coverage improvements that can be addressed in follow-up work without blocking merge.
