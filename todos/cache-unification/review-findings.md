# Code Review: cache-unification

**Reviewed**: 2026-01-15
**Reviewer**: Codex

## Completeness Verification

### Implementation Plan Status
- Unchecked tasks: 0
- Silent deferrals found: no

### Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
|-----------|-------------|-----------|------|--------|
| Session lifecycle events defined in `events.py` | teleclaude/core/events.py:201; teleclaude/core/events.py:208; teleclaude/core/events.py:260 | N/A (event constants) | NO TEST | ✅ |
| Adapters register handlers via `client.on()` | teleclaude/adapters/rest_adapter.py:105; teleclaude/adapters/redis_adapter.py:93; teleclaude/adapters/ui_adapter.py:70 | Adapter __init__ → client.on(...) | tests/unit/test_rest_adapter.py:640 | ✅ |
| Remote sessions update cache and trigger WS broadcasts | teleclaude/adapters/redis_adapter.py:1772; teleclaude/adapters/rest_adapter.py:807 | RedisAdapter._poll_session_events → cache.update_session → cache._notify → RESTAdapter._on_cache_change → ws.send_json | tests/integration/test_e2e_smoke.py:369 | ✅ |
| TUI handles events correctly | teleclaude/cli/tui/app.py:319 | WS thread → _process_ws_events → _apply_session_update/_apply_session_removal | NO TEST | ✅ |
| REST adapter handlers update cache (not bypass it) | teleclaude/adapters/rest_adapter.py:119 | AdapterClient.handle_event → RESTAdapter._handle_session_* → cache.update_session/remove_session | tests/unit/test_rest_adapter.py:576 | ✅ |
| REST adapter uses `TeleClaudeEvents.*` constants | teleclaude/adapters/rest_adapter.py:105 | RESTAdapter.__init__ → client.on(TeleClaudeEvents.*) | tests/unit/test_rest_adapter.py:640 | ✅ |
| Tests cover local session lifecycle → cache → WS flow | NOT FOUND | db.create_session/update_session → AdapterClient.handle_event → RESTAdapter._handle_session_* → cache.update_session/remove_session → RESTAdapter._on_cache_change → ws.send_json | NO TEST (local flow) | ❌ |
| Lint passes | NOT VERIFIED | N/A | NO TEST | ⚠️ |

**Verification notes:**
- The existing integration tests validate cache → WS broadcast behavior and simulate remote session updates, but there is no test that begins with a local session lifecycle event (DB or AdapterClient) and confirms the WS broadcast path.
- Lint/test execution is not evidenced in this review (not run here).

### Integration Test Check
- Main flow integration test exists: no
- Test file: N/A
- Coverage: N/A
- Quality: N/A

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| REST adapter handlers must update cache | ✅ | Implemented in RESTAdapter session event handlers. |
| REST adapter uses `TeleClaudeEvents.*` constants | ✅ | RESTAdapter subscriptions use TeleClaudeEvents constants. |
| Remote sessions update cache and trigger WS broadcasts | ✅ | Redis adapter updates cache; REST adapter broadcasts cache updates. |
| Tests cover local session lifecycle → cache → WS flow | ❌ | Missing integration test that starts from local DB/AdapterClient event. |
| Lint passes | ⚠️ | Not verified during review. |

## Critical Issues (must fix)

- None

## Important Issues (should fix)

- [tests] `tests/integration/test_e2e_smoke.py:183` - No integration test exercises the full local session lifecycle → cache → WS broadcast path. Current tests start at `cache.update_session()` and bypass the local event handlers, so regressions in RESTAdapter’s session event handlers would not be caught end-to-end.
  - Suggested fix: Add an integration test that triggers a local session lifecycle event (e.g., `db.create_session()` / `db.update_session()` with AdapterClient wired to RESTAdapter) and asserts the WebSocket receives the expected event.

## Suggestions (nice to have)

- None

## Strengths

- REST adapter now routes session lifecycle updates through the cache, aligning WS broadcasts with the single-source-of-truth model.
- Event subscriptions are standardized on `TeleClaudeEvents.*` constants with unit coverage.
- Session summary construction is centralized via `SessionSummary.from_db_session`, reducing duplication.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Missing integration test for local session lifecycle → cache → WS flow | Added `test_local_session_lifecycle_to_websocket` that validates DB → AdapterClient → REST adapter → Cache → WebSocket flow | 460943c |

**Fix details:**
- Created comprehensive integration test in `tests/integration/test_e2e_smoke.py:415`
- Test validates the complete local session lifecycle path:
  * `db.create_session()` triggers `SESSION_CREATED` event
  * `AdapterClient.handle_event()` dispatches to REST adapter handler
  * `RESTAdapter._handle_session_created_event()` updates cache
  * Cache update triggers `_on_cache_change` callback
  * WebSocket clients receive `session_updated` broadcast
- Uses real Database and AdapterClient instances (not mocks)
- Patches global `db` instance across all modules that import it
- All 60 integration tests pass

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. ~~Add an integration test for the local session lifecycle → cache → WS flow.~~ **FIXED**
