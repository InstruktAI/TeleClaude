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
| Session lifecycle events defined in `events.py` | `teleclaude/core/events.py:195` | N/A (event constants) | NO TEST | ✅ |
| Adapters register handlers via `client.on()` | `teleclaude/adapters/rest_adapter.py:106`; `teleclaude/adapters/redis_adapter.py:93`; `teleclaude/adapters/ui_adapter.py:70` | Adapter __init__ → `client.on(...)` | `tests/unit/test_rest_adapter.py:test_rest_adapter_subscriptions` | ✅ |
| Remote sessions update cache and trigger WS broadcasts | `teleclaude/adapters/redis_adapter.py:1772`; `teleclaude/adapters/rest_adapter.py:807` | RedisAdapter._poll_session_events → cache.update_session → cache._notify → RESTAdapter._on_cache_change → ws.send_json | `tests/integration/test_e2e_smoke.py:test_full_event_round_trip` | ❌ |
| TUI handles events correctly | `teleclaude/cli/tui/app.py:336` | WS thread → _process_ws_events → _apply_session_update/_apply_session_removal | NO TEST | ✅ |
| REST adapter handlers update cache (not bypass it) | `teleclaude/adapters/rest_adapter.py:119` | AdapterClient.handle_event → RESTAdapter._handle_session_* → cache.update_session/remove_session | `tests/unit/test_rest_adapter.py:test_handle_session_*` | ✅ |
| REST adapter uses `TeleClaudeEvents.*` constants | `teleclaude/adapters/rest_adapter.py:106` | RESTAdapter.__init__ → client.on(TeleClaudeEvents.*) | `tests/unit/test_rest_adapter.py:test_rest_adapter_subscriptions` | ✅ |
| Tests cover local session lifecycle → cache → WS flow | `tests/integration/test_e2e_smoke.py:415` | db.create_session → AdapterClient.handle_event → RESTAdapter._handle_session_created_event → cache.update_session → RESTAdapter._on_cache_change → ws.send_json | `tests/integration/test_e2e_smoke.py:test_local_session_lifecycle_to_websocket` | ✅ |
| Lint passes | NOT VERIFIED | N/A | NO TEST | ⚠️ |

**Verification notes:**
- RESTAdapter is constructed without a cache and wired later in `DaemonLifecycle.startup`. Because RESTAdapter only subscribes to cache updates during `__init__`, cache mutations (including those triggered by local lifecycle handlers) do not trigger `_on_cache_change` in production. This breaks WS broadcasts for both local and remote session updates despite passing tests that inject cache at construction time.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_e2e_smoke.py:test_local_session_lifecycle_to_websocket`
- Coverage: db.create_session → AdapterClient → REST handler → cache → WS broadcast
- Quality: Uses real DB + AdapterClient, but injects cache at RESTAdapter construction (does not mirror production cache wiring).

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| REST adapter handlers must update cache | ✅ | Handlers now call cache.update_session/remove_session. |
| REST adapter uses `TeleClaudeEvents.*` constants | ✅ | Subscriptions use TeleClaudeEvents constants. |
| Remote sessions update cache and trigger WS broadcasts | ❌ | RESTAdapter is not subscribed when cache is wired post-init, so WS broadcasts do not fire in production. |
| TUI handles events correctly | ✅ | Handlers present; no test coverage. |
| Tests cover local session lifecycle → cache → WS flow | ⚠️ | Test exists but doesn't exercise production cache wiring or update/remove flows. |
| Lint passes | ⚠️ | Not verified in this review. |

## Critical Issues (must fix)

- [code] `teleclaude/core/lifecycle.py:77` / `teleclaude/adapters/rest_adapter.py:101` - RESTAdapter subscribes to cache changes only during `__init__`, but the cache is wired **after** the adapter starts in `DaemonLifecycle.startup`. With the new cache-based handlers, WS updates never fire in production because `_on_cache_change` is never subscribed.
  - Suggested fix: Add a cache property setter in RESTAdapter (like RedisAdapter) that subscribes/unsubscribes, or explicitly call `cache.subscribe(rest_adapter._on_cache_change)` when wiring the cache in lifecycle startup.

## Important Issues (should fix)

- [tests] `tests/integration/test_e2e_smoke.py:415` - Integration test injects cache at RESTAdapter construction, so it does not cover the real startup path (cache wired after init). This would miss the production regression above.
  - Suggested fix: Add an integration test that sets `rest_adapter.cache` after construction (mirroring `DaemonLifecycle.startup`) and asserts WS updates are emitted.

## Suggestions (nice to have)

- [tests] `tests/integration/test_e2e_smoke.py:461` - Use `TeleClaudeEvents.*` constants instead of string literals for event registration to keep tests aligned with production conventions.

## Strengths

- REST adapter now routes session lifecycle updates through the cache, aligning WS broadcasts with the single-source-of-truth model.
- Session summary construction is centralized via `SessionSummary.from_db_session`, reducing duplication and drift.
- Integration coverage now exercises the local DB → AdapterClient → REST → cache → WS chain (under test wiring).

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| RESTAdapter cache subscription timing | Converted `cache` to property with setter that subscribes/unsubscribes automatically when cache is set (matching RedisAdapter pattern). Now WS broadcasts fire correctly when cache is wired post-init. | b249e0e |
| Integration test didn't cover production cache wiring | Added `test_rest_adapter_cache_wired_post_init` that constructs RESTAdapter without cache, then sets cache post-init (mirroring DaemonLifecycle.startup). Verifies WS broadcasts work correctly. | 2f9ede6 |

All critical and important issues have been addressed. Tests passing (61 passed). Ready for re-review.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Ensure RESTAdapter subscribes to cache updates when the cache is wired post-init (production path), so WS broadcasts fire correctly.
