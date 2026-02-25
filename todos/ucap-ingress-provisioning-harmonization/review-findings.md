# Review Findings: ucap-ingress-provisioning-harmonization

**Review round:** 1
**Reviewer approach:** Audit verification + test quality analysis
**Verdict:** REQUEST CHANGES

## Context

This build took an audit-and-verify approach: the builder concluded existing production code already satisfies R1–R4 and added 14 new tests to prove it. No production code was changed. Three parallel review lanes verified the audit claims against actual source code, evaluated test quality, and checked for code-level issues.

## Paradigm-Fit Assessment

1. **Data flow:** Tests exercise the existing data layer correctly — real `Db` instances for integration, proper mock setup for unit tests. No bypasses.
2. **Component reuse:** New tests reuse existing helpers (`DummyTelegramAdapter`, `MockTelegramAdapter`) appropriately.
3. **Pattern consistency:** Tests mostly follow established file conventions with minor deviations noted below.

## Audit Claim Verification

All four audit claims were independently traced against production source code:

| Claim                           | Verdict | Notes                                                                                                            |
| ------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| R1 — Command ingress mapping    | TRUE    | MCP actor synthesis in mapper is correctly placed in normalization layer                                         |
| R2 — Provenance write timing    | TRUE    | Ordering confirmed in both `process_message()` and `handle_voice()`                                              |
| R3 — Single provisioning funnel | TRUE    | All 7 output paths through `_route_to_ui()` → `ensure_ui_channels()` confirmed                                   |
| R4 — Routing-policy alignment   | TRUE    | One Telegram-specific block in `create_session` is identity metadata seeding, outside routing/provisioning scope |

The builder's conclusion that no production code changes were needed is correct.

## Critical

None.

## Important

### 1. R5 observability has zero test coverage

**Requirement:** R5.1 states "Error logs must identify adapter lane and session for ingress/provisioning failures." The implementation plan traceability explicitly maps R5 to Phase 3.

**Finding:** The production code does log correctly (`adapter_client.py:651-656` uses structured `[UI_LANE]` prefix with adapter type and session ID). However, no test verifies this logging invariant. A regression that drops the adapter identifier or session ID from the error log would go undetected.

**Fix:** Add one `caplog`-based test asserting that when an adapter lane raises, the ERROR log contains both the adapter key and the session ID.

### 2. Hardcoded `/tmp` database paths in integration tests

**Files:** `tests/integration/test_multi_adapter_broadcasting.py` (new tests at lines 771, 835)

**Finding:** New integration tests use hardcoded `/tmp/test_*.db` paths. The project convention is `tmp_path` fixture for test isolation. Under `pytest -n auto`, parallel workers could collide on these paths.

**Mitigation:** The existing tests in the same file already use this pattern (pre-existing), so this is a propagated antipattern rather than a new introduction. However, the new tests should not perpetuate it.

**Fix:** Use `tmp_path` fixture in the two new integration tests.

## Suggestions

### 3. `test_handle_voice_updates_last_input_origin_before_feedback` doesn't test ordering claim

The test short-circuits at `mock_voice.handle_voice = AsyncMock(return_value=None)`, so `_send_status` is never called. The docstring claims "before sending transcription status" but the send never happens. The test proves provenance is written when transcription returns `None` — a useful property, but the ordering claim in the docstring is not exercised. Consider: let the voice handler succeed with a transcription so feedback actually fires, then verify ordering.

### 4. MCP actor synthesis test is underspecified

`test_map_redis_mcp_message_actor_synthesis` asserts `"workstation" in cmd.actor_id`. The production contract is `system:{computer}:{session_id}`. A format change to `mcp-agent@{computer}` would pass the test while breaking the contract. Assert the `system:` prefix or structural format.

### 5. Inline imports duplicate module-level imports

`test_process_message_updates_last_input_origin_before_broadcast` and `test_handle_voice_updates_last_input_origin_before_feedback` import `ProcessMessageCommand` and `HandleVoiceCommand` inside the test body. Both are already imported at module level.

### 6. Cosmetic `ADAPTER_KEY` mutation in integration test

`test_broadcast_user_input_source_adapter_not_echoed` sets `discord.ADAPTER_KEY = "discord"` on a `MockTelegramAdapter` instance. Routing uses the dict key, not `ADAPTER_KEY`. The mutation is irrelevant and suggests a misunderstanding of the routing mechanism. Harmless but misleading.

---

## Fixes Applied

### Fix 1 — R5 observability test (Important #1)

**Issue:** No test verifying that ERROR log from `_run_ui_lane` includes adapter key and session ID.

**Fix:** Added `test_ui_lane_error_log_identifies_adapter_and_session` with `caplog` in `tests/unit/test_adapter_client_handlers.py`. Creates a `FailingAdapter` where `send_message` raises; `recover_lane_error` re-raises by default (UiAdapter contract), triggering the ERROR log. Asserts both `"telegram"` and `session.session_id[:8]` appear in the error message.

**Commit:** `9d5ee7fe`

---

### Fix 2 — Hardcoded `/tmp` paths (Important #2)

**Issue:** `test_ensure_channel_called_per_adapter_on_output` and `test_broadcast_user_input_source_adapter_not_echoed` used hardcoded `/tmp/*.db` paths, risking xdist collisions.

**Fix:** Added `tmp_path` fixture parameter to both tests; removed manual `Path.unlink` cleanup calls.

**Commit:** `9d5ee7fe`

---

### Fix 3 — Handle voice ordering test (Suggestion #3)

**Issue:** Test short-circuited with `return_value=None` so `_send_status` was never called — ordering claim not verified.

**Fix:** Replaced mock with `fake_handle_voice` coroutine that calls `send_message` callback (simulating "Transcribing..." status) before returning a transcription. Test now asserts `update_session` index precedes `send_message` index in `call_order`.

**Commit:** `fb67cbac`

---

### Fix 4 — MCP actor synthesis assertion (Suggestion #4)

**Issue:** `"workstation" in cmd.actor_id` would pass a format change like `mcp-agent@workstation`.

**Fix:** Changed to `cmd.actor_id.startswith("system:workstation:")` — asserts the full structural prefix.

**Commit:** `fb67cbac`

---

### Fix 5 — Inline imports removed (Suggestion #5)

**Issue:** `ProcessMessageCommand` and `HandleVoiceCommand` imported inline inside test bodies.

**Fix:** Added `ProcessMessageCommand` to module-level import block; removed both inline imports.

**Commit:** `fb67cbac`

---

### Fix 6 — Cosmetic ADAPTER_KEY mutation removed (Suggestion #6)

**Issue:** `discord.ADAPTER_KEY = "discord"` on a `MockTelegramAdapter` instance was misleading — routing uses dict key, not `ADAPTER_KEY`.

**Fix:** Removed the mutation.

**Commit:** `fb67cbac`
