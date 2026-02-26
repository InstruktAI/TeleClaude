# Review Findings: deployment-channels

## Paradigm-Fit Assessment

1. **Data flow**: The implementation correctly uses the hooks framework (`HandlerRegistry`, `Contract`, `HookDispatcher`) and loads config via established `load_project_config`. However, fan-out uses raw Redis Stream `xadd`/`xread` instead of the `EventBusBridge` specified in requirements — a paradigm deviation.
2. **Component reuse**: Good reuse of `HookEvent`, `Contract`, `PropertyCriterion`, `Target`, `HandlerRegistry`, `HookDispatcher`, and `RedisTransport._get_redis`. Background task lifecycle follows established `create_task` + `add_done_callback(_log_background_task_exception(...))` pattern.
3. **Pattern consistency**: New code follows existing daemon patterns for background consumers and contract registration.

---

## Critical

### 1. Double execution on originating daemon

**Files:** `handler.py:146-153`, `daemon.py:1675-1678,1742-1776`

When a GitHub event arrives, the handler both publishes a fan-out message to the Redis Stream AND executes `execute_update` locally via `asyncio.create_task`. The daemon's `_deployment_fanout_consumer` starts with `last_id = "$"` (reads messages published after startup). Since the originating daemon is already running, its own consumer reads the fan-out message it just published, deserializes it as a `deployment:version_available` event, and dispatches it back through the handler. The handler sees `event.source == "deployment"`, evaluates `should_update = True` (matching channel config), and spawns a second `execute_update` task.

Result: two concurrent `execute_update` tasks on the originating daemon — double git operations, double migration runs, race to `os._exit(42)`.

The loop-prevention guard (`event.source == "github"` check before `_publish_fanout`) prevents re-broadcasting but does not prevent re-execution.

**Fix:** Either embed a `daemon_id` (e.g. `config.computer.name`) in the fan-out message and skip self-originated messages in the consumer, or remove the local `execute_update` call from the github-source path and let the fan-out consumer be the sole execution trigger for all daemons (including the originating one).

---

## Important

### 2. Dead code: `_dispatch` stored but never used

**File:** `handler.py:25-26,29-36`

`configure_deployment_handler` accepts a `dispatch` callable and stores it in module-level `_dispatch`, but no code path ever reads `_dispatch`. The daemon passes `dispatcher.dispatch` into this function, but the fan-out uses `_get_redis` directly and local dispatch happens via the daemon's consumer. This is dead code that suggests incomplete refactoring.

**Fix:** Remove `_dispatch` from the module-level declaration and `configure_deployment_handler` signature.

### 3. Unreachable JSON parsing in fan-out reception path

**File:** `handler.py:106-113`

The code attempts to parse `event.properties.get("version_info")` as JSON. But `_publish_fanout` (lines 163-171) never sets a `version_info` property — it sets `channel`, `version`, and `from_version` individually. The JSON parse always fails or receives `""`, and the fallback at lines 119-120 is the actual execution path every time.

**Fix:** Remove lines 106-113. The fallback reconstruction from individual properties is correct and sufficient.

### 4. Synchronous `run_migrations()` blocks the asyncio event loop

**File:** `executor.py:136`

`run_migrations()` is synchronous — it performs filesystem I/O, module imports, and script execution. Called directly inside `async def execute_update`, it blocks the event loop during execution, stalling heartbeats, message delivery, and session handling.

**Fix:** Wrap in `await asyncio.to_thread(run_migrations, from_version, target_version)`.

### 5. Raw Redis Stream without maxlen / paradigm deviation

**File:** `handler.py:172`, `daemon.py:1742-1776`

The fan-out uses raw `redis.xadd` without a `maxlen` parameter, causing the stream to grow indefinitely. Additionally, this bypasses the project's `EventBusBridge` transport abstraction specified in requirements, creating a parallel event pathway that doesn't benefit from the transport layer's error handling or stream management.

**Fix:** Add `maxlen=1000` to the `xadd` call in `_publish_fanout`. Consider migrating to EventBusBridge for consistency.

### 6. Missing executor error path tests

**File:** `tests/unit/test_deployment_channels.py`

Implementation plan Task 2.1 calls for executor error path tests. Only migration failure is tested. Missing coverage:

- `git pull --ff-only` failure (alpha path, `executor.py:91-95`)
- `git fetch --tags` failure (beta/stable path, `executor.py:110-115`)
- `git checkout` failure (beta/stable path, `executor.py:127-130`)
- `make install` failure (`executor.py:165-169`)
- `make install` timeout (`executor.py:160-163`)

### 7. Missing integration test: HookEvent -> handler -> executor flow

**File:** `tests/unit/test_deployment_channels.py`

Implementation plan Task 2.1 explicitly specifies: "Integration test: HookEvent -> handler -> executor flow". No such test exists. All handler tests mock at the `asyncio.create_task` boundary. The wire-up between handler and executor — specifically that `execute_update` receives correct `channel` and `version_info` arguments — is untested.

### 8. Fan-out decision logic for deployment source undertested

**File:** `tests/unit/test_deployment_channels.py`

`test_handler_deployment_source_does_not_publish_fanout` only verifies no re-publish. It does not assert that `execute_update` IS called when the fan-out event matches the local channel config. Sub-paths for channel mismatch (beta event on alpha node), beta with valid version, and stable re-evaluation of `_is_within_pinned_minor` are all untested.

---

## Suggestions

### 9. `_read_version_from_pyproject` not directly tested

**File:** `executor.py:26-38`

The function has several branches (missing section, missing key, non-string version, exception fallback returning `"0.0.0"`). Only the happy path is exercised incidentally via executor tests.

### 10. `telec version` output changes untested

**File:** `teleclaude/cli/telec.py:1253-1270`

The `_handle_version` changes (loading deployment config, fallback to alpha, stable display with pinned minor) have no test coverage.

---

## Verdict: REQUEST CHANGES

The double-execution bug (Critical #1) is a deployment-safety issue that must be resolved before merge. Additionally, the dead code findings (#2, #3) and missing test coverage for error paths (#6, #7) indicate the implementation needs another pass.

---

## Fixes Applied

| Issue                                 | Fix                                                                                                          | Commit     |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ---------- |
| #2 Dead code `_dispatch`              | Removed `_dispatch` field and `dispatch` param from `configure_deployment_handler`; updated daemon call site | `e85b5b43` |
| #3 Unreachable JSON parsing           | Removed lines 106-113 (`version_info` JSON parse that always received `""`)                                  | `84ef78b3` |
| #5 No maxlen on xadd                  | Added `maxlen=1000` to `redis.xadd` in `_publish_fanout`                                                     | `0b33baa0` |
| #1 Double execution (Critical)        | Embed `daemon_id` in fan-out message; consumer skips messages with matching `daemon_id`                      | `a5ff0fb5` |
| #4 Blocking `run_migrations`          | Wrapped with `await asyncio.to_thread(run_migrations, ...)`                                                  | `35369270` |
| #6 Missing executor error paths       | Added tests for git pull, fetch, checkout, make install failure and timeout                                  | `cf570370` |
| #7 Missing integration test           | Added `test_integration_github_event_invokes_execute_update_with_correct_args` and beta variant              | `cf570370` |
| #8 Fan-out decision logic undertested | Added tests for alpha/beta/stable fan-out dispatch, channel mismatch, and stable pinned_minor evaluation     | `cf570370` |

Tests: 33 passed, 0 failed. Lint: PASSING.

Ready for re-review.
