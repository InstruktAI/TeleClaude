# DOR Gate Report: harmonize-agent-notifications

## Verdict: PASS — Score 9/10

## Gate Assessment

### 1. Intent & Success — PASS

- Problem is explicit: `notification` hooks bypass the canonical activity contract; web and TUI never see notification events.
- Goal is concrete: route notifications through `serialize_activity_event()` → `AgentActivityEvent` → event bus.
- Six functional requirements, each testable and traceable.

### 2. Scope & Size — PASS

- Atomic: one new event type, one new field, wired through 4 source files + 1 doc + tests.
- No cross-cutting concerns. Changes are localized to the activity contract module and its direct consumers.
- Fits a single builder session comfortably.

### 3. Verification — PASS

- `demo.md` provides concrete validation commands (Python one-liners + `make test`).
- Plan task 5 defines two specific test scenarios matching existing patterns in `test_activity_contract.py` and `test_agent_coordinator.py`.

### 4. Approach Known — PASS

- Pattern is fully established: `HOOK_TO_CANONICAL` mapping, `serialize_activity_event()`, `_emit_activity_event()` → `AgentActivityEvent` → event bus.
- This is copy-and-extend of a proven path. No architectural decisions needed.

### 5. Research Complete — PASS (auto-satisfied)

- No third-party dependencies introduced or modified.

### 6. Dependencies & Preconditions — PASS

- `ucap-cutover-parity-validation` delivered 2026-02-25 (commit `3ad15813`).
- No new configs, env vars, or external systems required.

### 7. Integration Safety — PASS

- Purely additive: new Literal member, new optional field (`message: str | None = None`), new mapping entry.
- Existing `handle_notification()` behavior preserved — emit call added after existing logic.
- All new fields have `None` defaults; no existing callers break.

### 8. Tooling Impact — PASS (auto-satisfied)

- No tooling or scaffolding changes.

## Plan-to-Requirement Fidelity — CLEAN

| Requirement                                                           | Plan Task   | Status |
| --------------------------------------------------------------------- | ----------- | ------ |
| R1: Add `agent_notification` to types + `_CANONICAL_TYPES`            | Task 1      | Traced |
| R2: Add `"notification": "agent_notification"` to `HOOK_TO_CANONICAL` | Task 1      | Traced |
| R3: Add `message` field to 3 locations                                | Tasks 1 + 2 | Traced |
| R4: Add `message` param to `_emit_activity_event()`                   | Task 3      | Traced |
| R5: Call `_emit_activity_event()` in `handle_notification()`          | Task 3      | Traced |
| R6: Update event-vocabulary.md                                        | Task 4      | Traced |

No contradictions found. Every plan task traces to a requirement. No plan task contradicts a requirement.

## Codebase Verification

- `CanonicalActivityEventType` at `activity_contract.py:27` — confirmed Literal type, needs new member.
- `_CANONICAL_TYPES` at `activity_contract.py:79` — confirmed frozenset, needs new member.
- `HOOK_TO_CANONICAL` at `activity_contract.py:41` — confirmed dict, needs new entry.
- `CanonicalActivityEvent` at `activity_contract.py:54` — confirmed frozen dataclass, needs `message` field.
- `serialize_activity_event()` at `activity_contract.py:106` — confirmed serializer, needs `message` kwarg.
- `AgentActivityEvent` at `events.py:496` — confirmed dataclass, needs `message` field.
- `_emit_activity_event()` at `agent_coordinator.py:469` — confirmed method, needs `message` kwarg.
- `handle_notification()` at `agent_coordinator.py:1286` — confirmed handler, needs emit call.
- Error hooks confirmed separate path via `ErrorEventContext` → `TeleClaudeEvents.ERROR` in `daemon.py:757`.

## Blockers

None.

## Score Rationale

9/10 — All gates pass. Minor deduction: test specification in the plan is adequate but could be slightly more explicit about verifying `message` field propagation end-to-end through the `_emit_activity_event` → `AgentActivityEvent` chain. Existing test patterns provide clear guidance for the builder.
