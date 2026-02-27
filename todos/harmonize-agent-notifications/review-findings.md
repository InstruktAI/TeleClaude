# Review Findings: harmonize-agent-notifications

## Verdict: APPROVE

## Paradigm-Fit Assessment

- **Data flow**: Follows the canonical contract pattern exactly. Hook event flows through `HOOK_TO_CANONICAL` mapping → `serialize_activity_event()` → `_emit_activity_event()` → `event_bus.emit()` — the established path for all activity events.
- **Component reuse**: Extends existing types (`CanonicalActivityEvent`, `AgentActivityEvent`, `_emit_activity_event`) with a new optional field rather than creating parallel paths. No copy-paste duplication.
- **Pattern consistency**: Mirrors the exact pattern established by existing canonical types (`tool_use` → `agent_output_update`, `agent_stop` → `agent_output_stop`). The new `notification` → `agent_notification` mapping is structurally identical.

## Requirements Traceability

| Requirement                                                                         | Status | Evidence                                                                           |
| ----------------------------------------------------------------------------------- | ------ | ---------------------------------------------------------------------------------- |
| R1: Add `agent_notification` to `CanonicalActivityEventType` and `_CANONICAL_TYPES` | Met    | `activity_contract.py:31`, `activity_contract.py:83`                               |
| R2: Add `"notification": "agent_notification"` to `HOOK_TO_CANONICAL`               | Met    | `activity_contract.py:47`                                                          |
| R3: Add `message: str \| None = None` to canonical and consumer events              | Met    | `activity_contract.py:75`, `events.py:514`, `activity_contract.py:119`             |
| R4: Add `message` param to `_emit_activity_event()` and wire through                | Met    | `agent_coordinator.py:476`, `agent_coordinator.py:501`, `agent_coordinator.py:511` |
| R5: Call `_emit_activity_event()` in `handle_notification()`                        | Met    | `agent_coordinator.py:1309`                                                        |
| R6: Update `event-vocabulary.md`                                                    | Met    | Three additions: canonical list, mapping table, payload fields                     |

## Critical

(none)

## Important

1. **Stale module docstring** — `activity_contract.py:7-10` lists only 3 canonical types, omitting `agent_notification`. The type list in the docstring is the first thing a reader sees and should match the actual vocabulary. This is a documentation-only gap; the code (Literal type, frozenset, mapping) is correct.

## Suggestions

1. **Parametrized test gap** — `test_serialize_activity_event_maps_to_canonical` (`test_activity_contract.py:28-33`) doesn't include `("notification", "agent_notification")`. A dedicated test exists, but the parametrized test is the canonical "all types" regression guard and should be authoritative.
2. **Completeness test gap** — `test_hook_to_canonical_covers_all_expected_hook_types` (`test_activity_contract.py:220`) — `required_hook_types` set doesn't include `"notification"`. Covered by a separate test, but the completeness assertion should be the single source of truth.
3. **Optional fields default test** — `test_serialize_activity_event_optional_fields_default_to_none` (`test_activity_contract.py:247-258`) doesn't assert `result.message is None` alongside the other optional fields.
4. **Consumer event docstring** — `AgentActivityEvent` docstring (`events.py:503-504`) mentions `(user_prompt_submit, agent_output_update, agent_output_stop)` without `agent_notification`.

## Manual Verification Evidence

- **Lint**: `make lint` passes — ruff format, ruff check, pyright (0 errors, 0 warnings).
- **Tests**: `make test` — 2403 passed, 106 skipped, 0 failures (16.86s).
- **Diff scope**: 3 production files, 1 doc file, 2 test files, 1 demo file changed. All within declared scope.
- **No deferrals**: No `deferrals.md` present; no silent deferrals detected.
- **Build state**: `state.yaml` marks `build: complete`. All 6 requirements traced and met.
- **Implementation plan clerical gap**: Task checkboxes in `implementation-plan.md` remain unchecked `[ ]` despite work being complete. Non-blocking — orchestrator confirmed build completion.
