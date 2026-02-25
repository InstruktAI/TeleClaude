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
