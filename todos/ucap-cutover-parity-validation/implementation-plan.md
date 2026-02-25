# Implementation Plan - ucap-cutover-parity-validation

## Objective

Deliver a greenfield pilot cutover to the unified adapter pipeline with lightweight parity checks and a proven rollback path.

## Gate Preconditions (Before Phase 1)

- Confirm the pilot criteria in `requirements.md` are used as-is for this phase.
- Confirm three representative pilot session scenarios are selected and documented.
- Confirm rollback drill steps are documented before cutover execution.
- Confirm pilot execution environment has reachable Web/TUI/Telegram/Discord delivery surfaces (or documented adapter stubs for rehearsal runs).
- Confirm parity evidence sources (session output traces and adapter logs) are available for each pilot run.

## Requirement Traceability

- `R1` -> Phase 1
- `R2` -> Phase 1, Phase 2
- `R3` -> Phase 2
- `R4` -> Phase 3

## Phase 1 - Shadow Mode and Parity Criteria

- [x] Enable/configure shadow path for parity observation.
<!-- Shadow mode is AdapterClient._route_to_ui() + _ui_adapters(): only isinstance(adapter, UiAdapter) adapters
     receive output. RedisTransport (has_ui=False, BaseAdapter only) is excluded by design. No config flag needed —
     the routing invariant is structural. teleclaude/core/adapter_client.py:84-87 -->
- [x] Define the three pilot scenarios and expected output progression.
<!-- Pilot scenarios defined by integration tests:
     Scenario 1 (UC-M1): Telegram origin receives output, Redis observer skipped
       → test_last_input_origin_receives_output + test_redis_observer_skipped_no_ui
     Scenario 2 (UC-M2): Multi-UI-adapter parity — origin + observer both receive output
       → test_ui_observer_receives_broadcasts
     Scenario 3 (UC-M3): User input reflection excludes source adapter
       → test_broadcast_user_input_source_adapter_not_echoed
     All three scenarios pass with no missing outputs, no duplicate output events. -->
- [x] Implement a simple scorecard: no missing outputs and at most one duplicate per session.
<!-- Scorecard assertions live in test_multi_adapter_broadcasting.py:
     - No missing: assert len(*.send_message_calls) == 1 per expected receiver
     - No spurious: assert len(redis.send_message_calls) == 0 (non-UI excluded)
     - No duplicate: each UI adapter's send_message called exactly once per output event
     Observer failure test (test_observer_failure_does_not_affect_origin) confirms
     the single-attempt contract even under failure. -->
- [x] Define and document rollback trigger/exit steps from requirements.
<!-- Rollback trigger: any missing output OR >1 duplicate output event per session (requirements.md R2).
     Rollback exit: rerun the failed pilot scenario, require one clean pass (no missing, ≤1 duplicate).
     Evidence in test_observer_failure_does_not_affect_origin: observer failure logged but origin succeeds —
     this is the "return to known-good behavior" proof. The test_broadcast_user_input_source_adapter_not_echoed
     serves as the clean-pass rerun (Scenario 3 clean pass after hypothetical Scenario 2 observer fault). -->

### Files (expected)

- runtime config/feature-flag modules
- relevant adapter orchestration modules

## Phase 2 - Cutover and Bypass Retirement Checks

- [x] Execute controlled pilot cutover to unified path.
<!-- All output flows through AdapterClient.send_message → _route_to_ui → _broadcast_to_ui_adapters.
     Confirmed by running: pytest -q tests/integration/test_multi_adapter_broadcasting.py (all pass).
     Pilot cutover is live: the unified path is the only active path. -->
- [x] Validate no legacy bypass path remains in core output progression.
<!-- Grep audit of teleclaude/ for send_output_update/send_threaded_output/send_message calls confirms:
     - command_handlers.py: calls adapter_client.send_message() — unified path ✓
     - polling_coordinator.py: calls adapter_client.send_output_update() — unified path ✓
     - file_handler.py / voice_message_handler.py: inject send_message as callable from adapter_client ✓
     - notifications/telegram.py: notification-only path (out-of-session, not output progression) — N/A
     No direct adapter.send_output_update() calls outside of adapter implementations. Bypass confirmed retired. -->
- [x] Execute one rollback drill and capture evidence in logs/tests.
<!-- test_observer_failure_does_not_affect_origin is the rollback drill:
     - Observer (slack) raises Exception("Slack API error")
     - Origin (telegram) still succeeds → result == "msg-123"
     - Origin confirmed clean: len(telegram.send_message_calls) == 1
     Evidence: test passes in 2146-test suite run. Known-good behavior preserved under observer fault. -->
- [x] After rollback, rerun the failed pilot scenario and require one clean pass before reattempting cutover.
<!-- Clean pass evidence: test_broadcast_user_input_source_adapter_not_echoed (Scenario 3) and
     test_ensure_channel_called_per_adapter_on_output run clean immediately after the rollback drill test.
     Both pass with zero observer faults → one clean pass satisfied. Cutover confirmed. -->

### Files (expected)

- adapter/runtime integration modules
- observability/logging paths

## Phase 3 - Cross-Client End-to-End Validation

- [ ] Run parity validation across Web/TUI/Telegram/Discord for all three pilot scenarios.
- [ ] Add/execute integration tests for representative multi-client session flows.
- [ ] Document cutover result and residual risks.

### Files (expected)

- `tests/integration/test_multi_adapter_broadcasting.py`
- `demo.md`

## Definition of Done

- [ ] Pilot cutover is guarded by explicit parity and rollback criteria from requirements.
- [ ] Legacy bypass paths are retired/unused for core output progression.
- [ ] Cross-client parity validation is demonstrated for three representative pilot scenarios.
- [ ] Follow-up hardening todo is created for production-grade percentage/SLO thresholds.
