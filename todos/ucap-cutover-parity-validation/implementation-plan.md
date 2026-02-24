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

- [ ] Enable/configure shadow path for parity observation.
- [ ] Define the three pilot scenarios and expected output progression.
- [ ] Implement a simple scorecard: no missing outputs and at most one duplicate per session.
- [ ] Define and document rollback trigger/exit steps from requirements.

### Files (expected)

- runtime config/feature-flag modules
- relevant adapter orchestration modules

## Phase 2 - Cutover and Bypass Retirement Checks

- [ ] Execute controlled pilot cutover to unified path.
- [ ] Validate no legacy bypass path remains in core output progression.
- [ ] Execute one rollback drill and capture evidence in logs/tests.
- [ ] After rollback, rerun the failed pilot scenario and require one clean pass before reattempting cutover.

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
