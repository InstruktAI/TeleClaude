# DOR Gate Report: harmonize-agent-notifications

**Assessed at**: 2026-02-27T13:15:00Z
**Verdict**: PASS (score 9/10)

## Gate Results

| #   | Gate               | Result | Notes                                                                             |
| --- | ------------------ | ------ | --------------------------------------------------------------------------------- |
| 1   | Intent & success   | Pass   | Problem, outcome, and 4 testable success criteria explicit                        |
| 2   | Scope & size       | Pass   | 4 source files + 1 doc — atomic, single session, clear non-scope                  |
| 3   | Verification       | Pass   | 4 automated demo scripts, make test/lint, manual verification                     |
| 4   | Approach known     | Pass   | Follows established HOOK_TO_CANONICAL pattern, proven `_emit_activity_event` flow |
| 5   | Research complete  | N/A    | No third-party dependencies                                                       |
| 6   | Dependencies       | Pass   | `ucap-cutover-parity-validation` delivered; all referenced files exist            |
| 7   | Integration safety | Pass   | Additive changes only; existing paths preserved; single-commit rollback           |
| 8   | Tooling impact     | N/A    | No tooling/scaffolding changes                                                    |

## Plan-to-Requirement Fidelity

| Plan Task                       | Requirement | Consistent |
| ------------------------------- | ----------- | ---------- |
| 1. Tag stripping utility        | FR-1        | Yes        |
| 2. Apply in handle_notification | FR-1, FR-6  | Yes        |
| 3. Extend canonical vocabulary  | FR-2        | Yes        |
| 4. Extend AgentActivityEvent    | FR-4        | Yes        |
| 5. Emit canonical event         | FR-3        | Yes        |
| 6. Update docs                  | FR-5        | Yes        |
| 7. Verification                 | SC 1-4      | Yes        |

No contradictions. Every requirement traces to at least one plan task.

## Observations (non-blocking)

1. **Broad regex**: Task 1 regex (`</?[\w-]+>`) strips all XML-like tags, not just
   `<task-notification>`. Requirements say "and similar XML wrapper tags" — intentional
   breadth. Builder may narrow to known tags if preferred.

2. **Test extension**: Existing `test_activity_contract.py` covers 4 hook mappings.
   Builder should extend parametrized test to include `("notification", "agent_notification")`.

## Assumptions

1. XML tag pattern is `<tag-name>...</tag-name>` (self-closing or wrapping).
   A broad regex stripping all XML-like tags is acceptable since notification messages
   are plain text that should never contain intentional XML.
2. The `message` field on `CanonicalActivityEvent` and `AgentActivityEvent` is additive
   and does not break existing consumers (they ignore unknown fields or use dataclass defaults).
3. Error hook (`error`) harmonization is intentionally out of scope — different semantic,
   different todo.

## Corrections Applied (draft → gate)

- Original plan included `error` → `agent_error` mapping. Removed: out of scope per requirements.
- Plan now includes explicit `CanonicalActivityEventType` Literal and `_CANONICAL_TYPES` frozenset updates.
- Plan now includes dependency graph and task-to-requirement tracing.

## Blockers

None.
