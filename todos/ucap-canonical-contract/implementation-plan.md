# Implementation Plan: ucap-canonical-contract

## Objective

Deliver a canonical outbound realtime activity contract and shared serialization/
validation utilities that downstream UCAP phases can adopt without redefining payload
semantics per adapter.

## Preconditions

- `transcript-first-output-and-hook-backpressure` remains `dor.status=pass`.
- No new third-party dependencies are required for this phase.
- Existing activity event tests remain as compatibility regression guards.

## Requirement Traceability

- `R1` -> Phases 1, 2, 5
- `R2` -> Phases 1, 2, 5
- `R3` -> Phases 2, 3, 5
- `R4` -> Phases 3, 5
- `R5` -> Phases 4, 5
- `R6` -> Phase 5

## Phase 1 - Contract Definition and Baseline Inventory (R1, R2)

- [x] Inventory current outbound activity payload producers and consumers.
- [x] Define canonical event vocabulary and schema fields for:
  - `user_prompt_submit`
  - `agent_output_update`
  - `agent_output_stop`
- [x] Define canonical routing metadata expectations (`message_intent`, `delivery_scope`)
      aligned with session output routing spec.
- [x] Record compatibility behavior for legacy consumers during migration.

### Files (expected)

- `docs/project/spec/event-vocabulary.md`
- `docs/project/spec/session-output-routing.md`
- `docs/project/design/architecture/agent-activity-streaming-target.md`
- `teleclaude/core/events.py`
- `teleclaude/api_models.py`

## Phase 2 - Shared Serializer/Validation Utilities (R2, R3)

- [x] Add a shared canonical contract utility module for serialization and validation.
- [x] Define explicit validation failure behavior (error reporting + non-crashing fallback).
- [x] Ensure utility APIs are adapter-agnostic and reusable by multiple producer paths.

### Files (expected)

- `teleclaude/core/events.py` and/or a new `teleclaude/core/*contract*.py` module
- `teleclaude/api_models.py`
- `teleclaude/core/adapter_client.py`

## Phase 3 - Producer Boundary Adoption (R3, R4)

- [x] Route poller/coordinator outbound activity emission through the shared canonical utility layer.
- [x] Remove ad-hoc producer-side payload shaping where canonical utility now applies.
- [x] Preserve existing output cadence and threaded/non-threaded behavior.

### Files (expected)

- `teleclaude/core/agent_coordinator.py`
- `teleclaude/core/polling_coordinator.py`
- `teleclaude/core/adapter_client.py`
- `teleclaude/api_server.py`

## Phase 4 - Compatibility Bridge (R5)

- [x] Implement translation from canonical contract to current legacy consumer payloads
      where needed.
- [x] Keep compatibility mapping centralized so legacy shape is derived from canonical events.
- [x] Verify no direct adapter-specific legacy shaping is reintroduced in core logic.

### Files (expected)

- `teleclaude/api_server.py`
- `teleclaude/cli/*` (only if local state reducers require mapping updates)
- compatibility helpers in `teleclaude/core/*` or `teleclaude/api/*`

## Phase 5 - Verification and Documentation Completion (R1-R6)

- [ ] Add/extend unit tests for canonical schema, serialization, validation failures,
      and event mapping behavior.
- [ ] Add regression tests ensuring current activity event consumers continue to pass.
- [ ] Update docs with canonical contract examples and migration notes.
- [ ] Update `demo.md` commands for deterministic validation execution.

### Files (expected)

- `tests/unit/test_agent_activity_events.py`
- `tests/unit/test_agent_activity_broadcast.py`
- `tests/unit/test_api_server.py`
- new contract-focused tests under `tests/unit/` (as needed)
- docs listed in Phase 1

## Rollout Notes

- This phase introduces contract primitives and compatibility mapping, but does not perform
  full Web/TUI bypass-path removal.
- Downstream alignment todos (`ucap-web-adapter-alignment`, `ucap-tui-adapter-alignment`,
  `ucap-ingress-provisioning-harmonization`) must consume this canonical contract rather than
  redefining event shape.

## Definition of Done

- [ ] Canonical outbound activity contract is documented and test-backed.
- [ ] Shared serializer/validator utilities are in place and used by producer paths.
- [ ] Compatibility bridge preserves existing consumer behavior during migration.
- [ ] No unresolved contradiction exists between contract docs and implementation plan tasks.
