# Code Review: cache-startup-warmup

**Reviewed**: 2026-01-14
**Reviewer**: Codex

## Completeness Verification

### Implementation Plan Status
- Unchecked tasks: 0
- Silent deferrals found: no

### Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
| --- | --- | --- | --- | --- |
| Remote projects are cached within seconds of daemon startup (not on first client connect). | teleclaude/adapters/redis_adapter.py:247 | daemon.start → AdapterClient.start → RedisAdapter.start → _ensure_connection_and_start_tasks → _populate_initial_cache → refresh_remote_snapshot → pull_remote_projects_with_todos | NO TEST | ❌ |
| Heartbeat payload includes `projects_digest` field. | teleclaude/adapters/redis_adapter.py:1249 | RedisAdapter.start → _ensure_connection_and_start_tasks → _heartbeat_loop → _send_heartbeat | NO TEST | ❌ |
| Adding or removing a project on a remote computer triggers cache refresh on peers within one heartbeat interval (~30s). | teleclaude/adapters/redis_adapter.py:326 | RedisAdapter.start → _ensure_connection_and_start_tasks → _peer_refresh_loop → refresh_peers_from_heartbeats → pull_remote_projects_with_todos | tests/integration/test_projects_digest_refresh.py::test_refresh_peers_triggers_pull_on_digest_change | ❌ |

**Verification notes:**
- The only integration test is fully mocked, so the main flow is not exercised end to end.

### Integration Test Check
- Main flow integration test exists: no (only mocked coverage)
- Test file: tests/integration/test_projects_digest_refresh.py
- Coverage: digest change triggers refresh logic with mocked Redis and cache
- Quality: over mocked, does not validate real Redis heartbeat ingestion or cache update behavior

### Requirements Coverage

| Requirement | Status | Notes |
| --- | --- | --- |
| Warmup on daemon startup (async, not waiting for client connect). | ⚠️ | Implemented in RedisAdapter startup path, but no test coverage. |
| Project digest in heartbeat (stable hash of project paths). | ⚠️ | Implemented via `_compute_projects_digest`, but no test for heartbeat payload. |
| Digest based invalidation (refresh on digest change, track last seen). | ⚠️ | Logic exists and has mocked test, but no end to end coverage. |

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [tests] tests/integration/test_projects_digest_refresh.py:1 - The integration test is fully mocked and does not exercise real Redis heartbeat ingestion or cache updates, so the main flow is unverified.
  - Suggested fix: Add an integration test that starts a Redis adapter with a real Redis instance (or a test double with real serialization), publishes a heartbeat containing `projects_digest`, and asserts the cache refresh occurs.
- [tests] teleclaude/adapters/redis_adapter.py:247 - No test verifies warmup runs on daemon startup and triggers a remote snapshot refresh.
  - Suggested fix: Add an integration test that starts the adapter and asserts `refresh_remote_snapshot` runs once on startup.
- [tests] teleclaude/adapters/redis_adapter.py:1249 - No test verifies heartbeat payload includes `projects_digest`.
  - Suggested fix: Add a unit test that runs `_send_heartbeat` and inspects the stored payload for `projects_digest`.

## Suggestions (nice to have)

- None.

## Strengths

- Warmup is implemented via `refresh_remote_snapshot`, reusing existing snapshot logic.
- Digest generation is deterministic and tested for ordering stability.
- Digest change handling logs failures and avoids silent refresh errors.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical or important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Replace the mocked integration test with an end to end test for digest driven refresh.
2. Add tests for startup warmup and heartbeat payload digest.

---

## Fixes Applied

| Issue | Fix | Commit |
| --- | --- | --- |
| [tests] tests/integration/test_projects_digest_refresh.py:1 - The integration test is fully mocked and does not exercise real Redis heartbeat ingestion or cache updates, so the main flow is unverified. | Replaced mocked test with shared MockRedisClient heartbeat flow and digest change assertions. | 197e2b2 |
| [tests] teleclaude/adapters/redis_adapter.py:247 - No test verifies warmup runs on daemon startup and triggers a remote snapshot refresh. | Added integration test that starts RedisAdapter and asserts snapshot refresh on startup. | 645c903 |
| [tests] teleclaude/adapters/redis_adapter.py:1249 - No test verifies heartbeat payload includes projects_digest. | Added unit assertion for projects_digest in heartbeat payload. | d468b48 |
