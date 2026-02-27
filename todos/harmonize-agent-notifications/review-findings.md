# Review Findings: harmonize-agent-notifications

## Verdict: APPROVE

## Review Round 2

### Scope

Reviewed all files changed since merge-base with main:

- `teleclaude/core/activity_contract.py`
- `teleclaude/core/agent_coordinator.py`
- `teleclaude/core/events.py`
- `docs/project/spec/event-vocabulary.md`
- `tests/unit/test_activity_contract.py`
- `tests/unit/test_agent_coordinator.py`
- `demos/harmonize-agent-notifications/demo.md`

### Verification

- `make test-unit`: 2300 passed, 106 skipped, 0 failed
- `make lint`: 0 errors, 0 warnings (ruff + pyright clean)
- No deferrals file exists

## Paradigm-Fit Assessment

- **Data flow**: Follows the canonical contract pattern exactly. Hook event flows through `HOOK_TO_CANONICAL` mapping, `serialize_activity_event()`, and `event_bus.emit()` — the established path for all activity events.
- **Component reuse**: Extends existing types (`CanonicalActivityEvent`, `AgentActivityEvent`, `_emit_activity_event`) with a new `message` field rather than creating parallel paths. Mirrors the `summary` field pattern used for `agent_stop`.
- **Pattern consistency**: Follows the exact pattern established by existing canonical types (`tool_use` -> `agent_output_update`, `agent_stop` -> `agent_output_stop`). No copy-paste duplication found.

## Requirements Traceability

| Requirement                                                                         | Status | Evidence                                                                           |
| ----------------------------------------------------------------------------------- | ------ | ---------------------------------------------------------------------------------- |
| R1: Add `agent_notification` to `CanonicalActivityEventType` and `_CANONICAL_TYPES` | Met    | `activity_contract.py:31`, `activity_contract.py:83`                               |
| R2: Add `"notification": "agent_notification"` to `HOOK_TO_CANONICAL`               | Met    | `activity_contract.py:47`                                                          |
| R3: Add `message: str \| None = None` to canonical and consumer events              | Met    | `activity_contract.py:75`, `events.py:514`, `activity_contract.py:119`             |
| R4: Add `message` param to `_emit_activity_event()` and wire through                | Met    | `agent_coordinator.py:476`, `agent_coordinator.py:501`, `agent_coordinator.py:511` |
| R5: Call `_emit_activity_event()` in `handle_notification()`                        | Met    | `agent_coordinator.py:1309`                                                        |
| R6: Update `event-vocabulary.md`                                                    | Met    | YAML list `:40`, mapping table `:57`, payload fields `:79`                         |

## Test Coverage Assessment

- **Serializer tests** (5 new): mapping, message pass-through, message default, HOOK_TO_CANONICAL presence, CTRL routing.
- **Coordinator tests** (2 new): end-to-end emission with real serializer, and isolated call-contract verification. Complementary strategies.
- **Pre-existing `test_activity_routing_is_always_ctrl`** automatically validates CTRL routing for `notification` since it iterates all `HOOK_TO_CANONICAL` entries.
- **Regression risk**: Low. Changes are purely additive — new canonical type, new optional field, new emission call. No existing behavior modified.

## Critical

(none)

## Important

1. **Stale module docstring** — `activity_contract.py:7-10` lists only 3 canonical types, omitting `agent_notification`. The docstring is the first reference point for the authoritative contract module.

2. **Stale `AgentActivityEvent` docstring** — `events.py:500-504` enumerates canonical types in a parenthetical list that is now incomplete (missing `agent_notification`).

## Suggestions

1. **Optional fields default test gap** — `test_serialize_activity_event_optional_fields_default_to_none` (`test_activity_contract.py:258`) asserts `tool_name`, `tool_preview`, and `summary` default to `None` but does not assert `message is None`. One-line addition.
2. **`handle_notification()` docstring** — `agent_coordinator.py:1291` says `"Handle notification event - input request."` but the method now has three responsibilities: local listener notification, remote forwarding, and canonical activity event emission.
3. **Parametrized test gap** — `test_serialize_activity_event_maps_to_canonical` (`test_activity_contract.py:28-33`) doesn't include `("notification", "agent_notification")`. Dedicated tests exist, but the parametrized test is the "all types" regression guard.
4. **Pre-existing: duplicate `Mapping` import** — `test_agent_coordinator.py:1,4` imports `Mapping` from both `collections.abc` and `typing`. Not introduced by this branch.

## Why No Critical Issues

- All six requirements are implemented and traced to specific code locations.
- The canonical activity contract pattern was followed precisely — no bypasses, no inline hacks.
- Copy-paste duplication was checked: `message` field is added via parameterization of existing components.
- Tests verify behavioral contracts at both the serializer and coordinator layers.
- The spec document (`event-vocabulary.md`) is fully consistent with the implementation.

## Manual Verification Evidence

- Lint: `make lint` passes (ruff format, ruff check, pyright — 0 errors).
- Tests: `make test-unit` — 2300 passed, 106 skipped, 0 failures.
- Diff scope: 4 production files, 1 doc file, 2 test files, 1 demo. All changes within declared scope.
- No deferrals.md present; no silent deferrals detected.
