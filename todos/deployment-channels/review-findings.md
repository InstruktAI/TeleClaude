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

**File:** `handler.py:46-51`

```python
expected_prefix = f"{pinned_minor}."
return version.startswith(expected_prefix) and version.count(".") == 2
```

`"1.20.0".startswith("1.2.")` is `True`. A stable node pinned to `1.2` would accept a `1.20.x` release. This is a real logic bug — the existing `parse_version` helper in `teleclaude/deployment/__init__.py` already validates proper integer parts and should be used instead:

```python
def _is_within_pinned_minor(version: str, pinned_minor: str) -> bool:
    if not version or not pinned_minor:
        return False
    try:
        from teleclaude.deployment import parse_version
        parts = pinned_minor.split(".")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            return False
        pin_major, pin_minor = int(parts[0]), int(parts[1])
        v_major, v_minor, _ = parse_version(version)
        return v_major == pin_major and v_minor == pin_minor
    except ValueError:
        return False
```

#### 15. `make install` subprocess not killed on timeout

**File:** `executor.py:158-163`

`asyncio.wait_for` cancels the `communicate()` coroutine but does not terminate the underlying OS process. After the `TimeoutError` is caught and `execute_update` returns, the `make install` subprocess continues running in the background — consuming resources, potentially completing a partial install, and holding file locks.

```python
except asyncio.TimeoutError:
    try:
        install.kill()
        await install.wait()
    except ProcessLookupError:
        pass
    logger.error("Deploy: make install timed out after 60s")
    await update_status({"status": "update_failed", "error": "make install timed out"})
    return
```

### Important

#### 16. Fire-and-forget `execute_update` task with no done callback

**File:** `handler.py:141`

```python
asyncio.create_task(execute_update(channel, version_info, get_redis=_get_redis))
```

Every other background task in the daemon attaches `add_done_callback(self._log_background_task_exception(...))` (daemon.py lines 1678, 1732, 1738). This task is created without storage or callback. If the task raises `CancelledError` during shutdown or an exception escapes the outer handler, it is silently swallowed by asyncio.

```python
def _log_task_exception(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        logger.error("Deploy: execute_update task failed: %s", exc, exc_info=exc)

task = asyncio.create_task(execute_update(channel, version_info, get_redis=_get_redis))
task.add_done_callback(_log_task_exception)
```

#### 17. Beta fan-out accepted by stable node — channel mismatch not filtered

**File:** `handler.py:113`

```python
elif channel in ("beta", "stable") and version_info.get("channel") in ("beta", "stable"):
```

A stable node receiving a beta fan-out enters this branch. If the beta release version happens to match the stable node's pinned minor (e.g. beta publishes `1.2.4`, stable pins `1.2`), the stable node will deploy a beta release. Per the decision matrix, stable nodes should only act on stable-channel releases.

Fix: match `channel == fan_channel`:

```python
elif channel in ("beta", "stable") and version_info.get("channel") == channel:
```

#### 18. Fanout consumer dies permanently on Redis startup failure

**File:** `daemon.py:1752-1756`

When `redis_transport._get_redis()` raises at consumer startup, the consumer logs and returns — permanently. No restart is attempted. The in-loop error handler (line 1783) retries with a 5s backoff for transient Redis errors, but the startup failure exits before entering the loop.

Fix: move Redis connection acquisition inside the loop with retry logic.

### Suggestions

#### 19. Dead code: `if not version_info:` guard always True

**File:** `handler.py:107`

`version_info` is `{}` at line 80 and only populated inside the `github` branch. When the `deployment` branch is entered, the guard is always True. Remove the guard for clarity.

#### 20. `_read_version_from_pyproject` silent fallback to "0.0.0"

**File:** `executor.py:36`

The `except` block returns "0.0.0" with no log message. This value feeds into `run_migrations` as the target version, which could cause incorrect migration behavior. At minimum, log a warning.

#### 21. Exit code 42 should be a named constant

**File:** `executor.py:175`

Replace magic number with `_RESTART_EXIT_CODE = 42` and add a comment referencing launchd `KeepAlive`.

#### 22. Test: `test_handler_deployment_source_does_not_publish_fanout` leaks task

**File:** `tests/unit/test_deployment_channels.py:275`

The test does not patch `asyncio.create_task`. The alpha fan-out event triggers `execute_update`, scheduling the real coroutine. Add `patch("asyncio.create_task", side_effect=_create_task_closing_coro)` to match other tests.

Suggestions #9-13 from round 1 remain open and are carried forward.

---

## Fixes Applied (Round 2 findings)

| #   | Issue                                                      | Fix                                                                         | Commit     |
| --- | ---------------------------------------------------------- | --------------------------------------------------------------------------- | ---------- |
| 14  | `_is_within_pinned_minor` prefix match accepts wrong minor | Replaced string `startswith` with `parse_version` integer compare           | `f48323b4` |
| 15  | `make install` subprocess not killed on timeout            | Added `install.kill()` + `await install.wait()` after `TimeoutError`        | `68299f24` |
| 16  | `execute_update` task fire-and-forget, no done callback    | Added `_log_execute_update_task_exception` callback via `add_done_callback` | `43e06e81` |
| 17  | Beta fan-out accepted by stable node                       | Changed condition to `version_info.get("channel") == channel`               | `21f188e7` |
| 18  | Fanout consumer dies permanently on Redis startup failure  | Moved `_get_redis()` call inside the retry loop                             | `3924e009` |

---

## Verdict: REQUEST CHANGES

Round 1 findings (1 Critical, 7 Important) are all resolved. However, deeper analysis reveals 2 new Critical bugs (#14: prefix match accepts wrong minor versions; #15: orphaned subprocess on timeout) and 3 Important issues (#16-18). These should be fixed before merge.
