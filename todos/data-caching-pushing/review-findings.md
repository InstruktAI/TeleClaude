# Code Review: data-caching-pushing

**Reviewed**: 2026-01-11
**Reviewer**: Claude Opus 4.5 (TeleClaude)
**Review Type**: Full review of Phases 0-6 implementation

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Instant reads (TUI reads from local cache) | ✅ | DaemonCache provides instant reads for REST endpoints |
| Event-driven updates (push to interested daemons) | ✅ | Redis adapter pushes session events to peers via streams |
| Interest-based activation (cache activates when TUI connected) | ✅ | WebSocket subscriptions track interest, advertised in heartbeat |
| Minimal traffic (only push to interested daemons) | ✅ | `_get_interested_computers()` filters to only interested peers |
| Phase 0: Fix REST/MCP Separation | ✅ | MCPServerProtocol removed, command_handlers used directly |
| Phase 1: DaemonCache Foundation | ✅ | Cache class created with TTL, interest, notifications |
| Phase 2: REST Reads from Cache | ✅ | Endpoints merge local + cached remote data |
| Phase 3: WebSocket Server | ✅ | `/ws` endpoint with subscription handling |
| Phase 4: Interest Management | ✅ | Interest tracked in cache, included in heartbeat |
| Phase 5: Event Push | ✅ | Redis adapter pushes to `session_events:{computer}` streams |
| Phase 6: Event Receive | ✅ | Redis adapter polls stream and updates cache |
| Phase 7: TUI Refactor | ⏸️ | Deferred (server infrastructure complete, client pending) |
| Linting passes | ✅ | pyright/mypy: 0 errors |
| Tests pass | ✅ | 692 unit tests pass in 3.72s |

## Critical Issues (must fix)

**1. [Fire-and-forget task] `redis_adapter.py:1086` - Unmonitored asyncio task swallows exceptions**

```python
asyncio.create_task(self._push_session_event_to_peers(event, data))
```

If `_push_session_event_to_peers` raises an exception, it will be silently lost. Users will see stale data without any indication of why events stopped pushing.

- Suggested fix: Add exception callback to log failures:
  ```python
  task = asyncio.create_task(self._push_session_event_to_peers(event, data))
  task.add_done_callback(lambda t: logger.error("Push task failed: %s", t.exception()) if t.done() and not t.cancelled() and t.exception() else None)
  ```

**2. [Fire-and-forget task] `rest_adapter.py:476` - Unmonitored WebSocket send swallows exceptions**

```python
asyncio.create_task(ws.send_json({"event": event, "data": data}))
```

The except block on lines 477-478 will NEVER catch exceptions from this task because `asyncio.create_task()` returns immediately. WebSocket clients silently miss updates.

- Suggested fix: Add done callback that removes dead clients:
  ```python
  task = asyncio.create_task(ws.send_json({"event": event, "data": data}))
  def on_done(t: asyncio.Task, client: WebSocket = ws) -> None:
      if t.done() and t.exception():
          logger.warning("WebSocket send failed, removing client: %s", t.exception())
          self._ws_clients.discard(client)
          self._client_subscriptions.pop(client, None)
  task.add_done_callback(on_done)
  ```

## Important Issues (should fix)

**1. [Resource leak] `redis_adapter.py:122-128` - Cache subscription not cleaned up on replacement**

When cache is replaced via the property setter, the old cache subscription is not cleaned up. If cache is replaced, the old cache will still call `_on_cache_change`.

- Suggested fix: Unsubscribe from old cache before setting new one:
  ```python
  @cache.setter
  def cache(self, value: "DaemonCache | None") -> None:
      if self._cache:
          self._cache.unsubscribe(self._on_cache_change)
      self._cache = value
      if value:
          value.subscribe(self._on_cache_change)
  ```

**2. [Resource leak] `rest_adapter.py:57-58` - Same issue in REST adapter**

Cache subscription added in `__init__` but never cleaned up on stop or cache replacement.

- Suggested fix: Add cleanup in `stop()` method

**3. [Missing cleanup] `rest_adapter.py:497-507` - WebSocket state not cleared on stop**

When RESTAdapter stops, WebSocket connections and cache interest are not cleaned up. Stale interest remains in cache.

- Suggested fix: Clear interest and close WebSocket clients on stop

**4. [Silent fallback] `redis_adapter.py:843-846` - Base64 decode failure has no logging**

```python
try:
    title = base64.b64decode(args[2]).decode()
except Exception:
    title = None
```

No logging when decode fails. Session titles mysteriously missing with no trace.

- Suggested fix: Add `logger.warning("Failed to decode title from base64: %s", e)`

**5. [Silent fallback] `redis_adapter.py:1015-1016` - JSON decode failure uses empty dict**

Invalid JSON in system command args silently becomes empty dict. Commands fail mysteriously.

- Suggested fix: Add `logger.warning("Invalid JSON in system command args: %s", args_json[:100])`

**6. [Silent fallback] `redis_adapter.py:631-634` - Invalid timestamp silently uses "now"**

Stale peers appear as recently active due to silent fallback.

- Suggested fix: Add warning log when fallback is used

## Suggestions (nice to have)

1. **[Complexity]** `redis_adapter.py:802-963` - `_handle_incoming_message()` is 160+ lines. Consider dict-based dispatch per coding directives.

2. **[Duplication]** `redis_adapter.py:204-238` - Connect/reconnect have nearly identical backoff loops. Extract common helper.

3. **[Duplication]** `redis_adapter.py:248-281` - Repetitive task cancellation pattern. Extract `_cancel_task()` helper.

4. **[Duplication]** `redis_adapter.py:1131-1182` - Heartbeat parsing duplicated from `discover_peers()`. Extract `_iter_heartbeat_data()` generator.

5. **[Logging]** Several `continue` statements skip entries without logging (lines 1152, 1158, 1216, 1221). Add DEBUG/TRACE level logs.

6. **[Types]** Callback type `Callable[[str, object], None]` is loose. Consider discriminated union event types.

7. **[Code]** TTL values (60, 300) are magic numbers. Extract to class constants.

## Strengths

1. **Comprehensive test coverage** - `tests/unit/test_cache.py` has 27 tests covering TTL, notifications, filtering, edge cases
2. **Defensive coding** - `set_interest()` and `get_interest()` correctly use `.copy()` to prevent external mutation
3. **Exception handling in callbacks** - `_notify()` properly catches callback errors without crashing (tested)
4. **Clean architecture** - DaemonCache separates concerns cleanly from adapters
5. **All tests pass** - 692 unit tests pass in 3.72s
6. **Linting clean** - pyright and mypy show 0 errors, ruff passes
7. **Good logging** - Key execution points logged at appropriate levels

## Verdict

**[x] REQUEST CHANGES** - Fix critical issues first

### Priority fixes:

1. **Critical**: Add exception callbacks to fire-and-forget asyncio tasks (prevents silent failures in production)
2. **Important**: Clean up cache subscriptions on adapter stop/replacement (prevents resource leaks)
3. **Important**: Add warning logs for silent fallbacks (enables debugging)

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Critical #1: Fire-and-forget task in redis_adapter.py:1086 | Added exception callback to log failures in `_push_session_event_to_peers` | 4aed5aa |
| Critical #2: Fire-and-forget task in rest_adapter.py:476 | Added done callback to remove dead WebSocket clients on send failure | 0ba3448 |
| Important #1: Cache subscription leak in redis_adapter.py:122-128 | Unsubscribe from old cache before setting new one | 4aed5aa |
| Important #2: Cache subscription leak in rest_adapter.py | Added cache unsubscribe in stop() method | 0ba3448 |
| Important #3: WebSocket state not cleared on stop | Close all WebSocket clients and clear interest in stop() method | 0ba3448 |
| Important #4: Base64 decode failure silent (redis_adapter.py:843-846) | Added warning log when decode fails | 4aed5aa |
| Important #5: JSON decode failure silent (redis_adapter.py:1015-1016) | Added warning log when invalid JSON in system command args | 4aed5aa |
| Important #6: Invalid timestamp fallback silent (redis_adapter.py:631-634) | Added warning log when timestamp parsing fails | 4aed5aa |

**Tests:** All 731 tests pass (unit + integration)

**Commits:**
- `4aed5aa` - fix(data-caching-pushing): add exception callbacks to fire-and-forget tasks
- `0ba3448` - fix(data-caching-pushing): add exception callback for WebSocket send tasks

---

## Previous Reviews

This review supersedes the earlier Phase 0-2 review. Phases 3-6 have been added since then, introducing new critical issues around async task exception handling that must be addressed.
