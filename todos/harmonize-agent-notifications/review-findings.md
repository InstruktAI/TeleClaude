# Review Findings: harmonize-agent-notifications (Round 2)

## Verdict: APPROVE

No code changes since Round 1 approval (baseline `7e75e328`). All commits since baseline are state.yaml reconciliation. Round 1 findings still apply; reaffirmed below.

## Paradigm-Fit Assessment

- **Data flow**: Follows the canonical contract pattern exactly. Hook event flows through `HOOK_TO_CANONICAL` mapping, `serialize_activity_event()`, and `event_bus.emit()` — the established path for all activity events.
- **Component reuse**: Extends existing types (`CanonicalActivityEvent`, `AgentActivityEvent`, `_emit_activity_event`) rather than creating parallel paths. No copy-paste duplication.
- **Pattern consistency**: Follows the exact pattern established by existing canonical types (`tool_use` → `agent_output_update`, `agent_stop` → `agent_output_stop`).

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

1. **Stale module docstring** — `activity_contract.py:7-10` lists only 3 canonical types, omitting `agent_notification`. The type list in the docstring is the first thing a reader sees and should match the actual vocabulary.

## Suggestions

1. **Parametrized test gap** — `test_serialize_activity_event_maps_to_canonical` (`test_activity_contract.py:28-33`) doesn't include `("notification", "agent_notification")`. The parametrized test is the canonical "all types" regression guard and should be authoritative.
2. **Completeness test gap** — `test_hook_to_canonical_covers_all_expected_hook_types` (`test_activity_contract.py:220`) — `required_hook_types` set doesn't include `"notification"`.
3. **Optional fields default test** — `test_serialize_activity_event_optional_fields_default_to_none` (`test_activity_contract.py:247-258`) doesn't assert `result.message is None` alongside the other optional fields.
4. **Consumer event docstring** — `AgentActivityEvent` docstring (`events.py:500`) mentions "(tool_use, tool_done, agent_stop)" without `notification`.

## Manual Verification Evidence

- Lint: `make lint` passes (ruff format, ruff check, pyright — 0 errors, 0 warnings).
- Tests: `make test` — 2403 passed, 106 skipped, 0 failures.
- Diff scope: 7 production/doc files changed, 2 test files changed. All changes within declared scope.
- No deferrals.md present; no silent deferrals detected.
- No code changes since Round 1 baseline — re-review triggered by state reconciliation only.
