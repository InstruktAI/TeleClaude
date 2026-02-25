# Review Findings - ucap-tui-adapter-alignment

## Verdict: APPROVE

## Summary

Round 2 re-review after fix-review commit `c41cf4be`. Both Important findings from round 1 are properly resolved. The implementation correctly threads `canonical_type` through the full WS event → DTO → Message → handler chain. The handler dispatches on canonical vocabulary instead of hook types. Structured observability fields are present on both debug and warning log paths. Handler dispatch tests cover all branches including edge cases.

---

## Critical

None.

## Important

None.

## Suggestions

### 1. Redundant inline imports in data-holding tests

**File:** `tests/unit/test_threaded_output_updates.py:349,362,373,386`

Tests 1-4 (`test_agent_activity_*`) contain inline `from teleclaude.cli.tui.messages import AgentActivity` despite the module-level import at line 6. The inline imports are redundant and inconsistent with the handler tests which use the module-level import. Not a behavioral issue.

### 2. Serializer tests still duplicate `test_activity_contract.py`

Tests 5-8 exercise `serialize_activity_event` directly with the same mappings covered by `test_activity_contract.py`. Maintenance cost without differentiated regression value. Consider consolidating in a future cleanup.

---

## Paradigm-Fit Assessment

1. **Data flow**: Correct. WS event → `AgentActivityEventDTO` → `AgentActivityEvent` → `AgentActivity` Message → `on_agent_activity` handler. No bypass paths. `canonical_type` threaded through all layers as optional field.
2. **Component reuse**: Correct. `AgentActivity` message class extended in place (not duplicated). Handler refactored in situ.
3. **Pattern consistency**: Correct. Handler structure matches sibling handlers in `app.py`. Structured logging uses `extra` dicts per `instrukt_ai_logging` convention. Tests follow existing file patterns.

## Requirement Verification

| Requirement                        | Status | Evidence                                                                                |
| ---------------------------------- | ------ | --------------------------------------------------------------------------------------- |
| R1: Canonical contract consumption | Met    | `on_agent_activity` dispatches on `canonical_type`, not `activity_type`                 |
| R2: Bypass removal                 | Met    | Old `activity_type` branches removed; `canonical is None` guard prevents untyped events |
| R3: Presentation boundary          | Met    | Tool preview formatting stays in TUI handler; canonical payload not mutated             |
| R4: Observability parity           | Met    | Both debug log (line 535) and warning log (line 542) carry structured `extra` fields    |

## Round 1 Finding Resolution

### Finding #1 — R4 structured log fields on warning path

**Status:** Resolved in `c41cf4be`.
**Verification:** `app.py:546` now includes `extra={"lane": "tui", "canonical_type": None, "session_id": message.session_id}`.

### Finding #2 — Handler dispatch logic untested

**Status:** Resolved in `c41cf4be`.
**Verification:** 9 handler-level tests added covering all branches: `canonical is None` early return, `user_prompt_submit`, `agent_output_stop` with/without summary, `agent_output_update` with tool (prefix stripping, no prefix, preview == name), `agent_output_update` without tool, and unknown canonical fallthrough.

## Build Checklist Validation

- Implementation plan tasks: All checked
- Build section in quality-checklist: All checked
- Tests pass: 2132 passed, 106 skipped
- No deferrals.md
- Commits: `0393dad6` (feat), `ae6b1f0c` (build), `c41cf4be` (fix-review)

## Review Round

2 of 3.
