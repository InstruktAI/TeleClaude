# Review Findings: ucap-canonical-contract

## Verdict: APPROVE

## Summary

Clean, well-structured delivery. The canonical contract module is minimal, focused, and
follows established codebase patterns. All 6 functional requirements are satisfied. 25 new
tests cover serializer success/failure, validation, routing metadata, mapping completeness,
and end-to-end integration through the coordinator and API server.

## Requirements Traceability

| Req | Status | Evidence                                                                                                                                            |
| --- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | Met    | `CanonicalActivityEventType` Literal + `HOOK_TO_CANONICAL` mapping in `activity_contract.py:27-46`; documented in `event-vocabulary.md`             |
| R2  | Met    | `CanonicalActivityEvent` frozen dataclass with 6 required + 3 optional fields (`activity_contract.py:54-72`); field tables in `event-vocabulary.md` |
| R3  | Met    | `serialize_activity_event()` + `_validate_canonical_event()` (`activity_contract.py:83-161`); non-crashing behavior tested                          |
| R4  | Met    | All 5 producer call sites in `agent_coordinator.py` route through `_emit_activity_event()` which calls `serialize_activity_event()`                 |
| R5  | Met    | Hook event type preserved in `AgentActivityEvent.event_type`; canonical fields optional + `exclude_none=True` on DTO dump (`api_server.py:287`)     |
| R6  | Met    | `event-vocabulary.md`, `session-output-routing.md`, `agent-activity-streaming-target.md` all updated                                                |

## Paradigm-Fit Assessment

1. **Data flow**: Follows existing event bus pattern (`coordinator → event_bus.emit → api_server handler → DTO → WebSocket`). No bypass.
2. **Component reuse**: Extends `AgentActivityEvent` and `AgentActivityEventDTO` with optional fields rather than duplicating. No copy-paste.
3. **Pattern consistency**: Frozen dataclasses, `Literal` types, `model_dump(exclude_none=True)`, structured logging with `extra=` — all match established conventions.

## Critical

None.

## Important

None.

## Suggestions

None.

## Why No Issues

1. **Paradigm fit**: Verified event bus data flow, frozen dataclass pattern, DTO serialization, and structured logging all match adjacent code. Contract module imports only `dataclasses`, `typing`, and `instrukt_ai_logging` — no adapter or transport leakage.
2. **Requirements validation**: Each of the 6 functional requirements traced to specific files and line ranges. Producer integration verified by grepping all `_emit_activity_event` call sites (5 calls in `agent_coordinator.py`). Compatibility bridge verified by confirming `exclude_none=True` on DTO dump and optional canonical fields.
3. **Copy-paste duplication**: Checked for duplicate payload shaping in `polling_coordinator.py` and `adapter_client.py` — neither emits activity events. All activity emission goes through the single `_emit_activity_event` method.

## Test Coverage Assessment

- **`test_activity_contract.py`** (20 tests): Serializer success for all 4 hook types, required field population, optional field defaults, routing metadata, failure paths (unknown type, empty session_id, empty timestamp), logging assertions, mapping completeness.
- **`test_agent_activity_broadcast.py`** (+2 tests): Canonical fields present in broadcast when event carries them; excluded when absent (legacy path).
- **`test_agent_activity_events.py`** (+3 tests): End-to-end coordinator integration for `tool_use`, `agent_stop`, and `tool_done` — verifies canonical fields on emitted events.
- **Regression risk**: Low. Existing activity event tests unmodified and passing. New fields are optional with `None` defaults.

## Manual Verification

Not applicable — this delivery introduces internal contract primitives and serialization utilities with no user-facing UI changes. Behavior is fully covered by automated tests.
