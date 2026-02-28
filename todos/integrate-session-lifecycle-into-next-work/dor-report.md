# DOR Report: integrate-session-lifecycle-into-next-work

## Gate Verdict

**Assessed at:** 2026-02-28T14:30:00Z
**Phase:** Gate (final)
**Score:** 8
**Status:** PASS

---

### Gate 1: Intent & Success — PASS

Problem statement is explicit: next-work orchestration lacks session lifecycle discipline, causing context-destroying worker churn during review friction and relying on AI reasoning for artifact verification that should be mechanical.

Three outcomes:

1. Direct peer conversation replaces fix-review dispatch churn (R1)
2. Mechanical CLI gate replaces AI artifact checking (R2)
3. Session lifecycle principle wired into orchestrator context (R3)

Eight success criteria are concrete and testable: CLI exit codes, observable session behavior, grep-verifiable documentation changes, and unit test existence.

### Gate 2: Scope & Size — PASS

Three independent workstreams with clear build order (verification gate first, peer conversation second, principle wiring third). Changes are concentrated in:

- `teleclaude/core/next_machine/core.py` (verify_artifacts function + POST_COMPLETION modifications)
- `teleclaude/cli/telec.py` + `teleclaude/cli/tool_commands.py` (CLI registration)
- `agents/commands/next-work.md` + `agents/commands/next-fix-review.md` (documentation)
- `tests/unit/test_next_machine_verify_artifacts.py` (new test file)

Fits a single focused build session. Each workstream is independently testable.

### Gate 3: Verification — PASS

- Artifact verification: unit tests covering pass/fail for build and review phases (Task 4.1)
- Direct peer conversation: observable through session listing during a review cycle
- Session lifecycle wiring: grep-verifiable in command artifact
- Integration: existing `make test` suite covers state machine routing

### Gate 4: Approach Known — PASS

All patterns confirmed in codebase:

- `run_build_gates()` at core.py:388 is the model for `verify_artifacts()`
- `POST_COMPLETION` dict at core.py:147 already handles per-command orchestration logic
- `telec sessions send --direct` confirmed in CLI_SURFACE with full flag/notes support
- CLI subcommand registration pattern established; `tool_commands.py` confirmed present
- `review_round` / `max_review_rounds` / `_is_review_round_limit_reached()` confirmed for safety cap

### Gate 5: Research Complete — N/A

No third-party dependencies.

### Gate 6: Dependencies & Preconditions — PASS

All required CLI capabilities confirmed present:

- `telec sessions send --direct` (idempotent link establishment)
- `telec sessions run --command /next-fix-review`
- `telec sessions end <session_id>`
- State machine routing infrastructure in core.py

No external dependencies. No unresolved config or env requirements.

### Gate 7: Integration Safety — PASS

Changes are incremental and backward-compatible:

- `verify_artifacts()` is additive (new function, no modification to existing behavior)
- POST_COMPLETION APPROVE path unchanged; REQUEST CHANGES path adds peer conversation with existing fix-review dispatch as fallback when no reviewer session is alive
- Documentation changes are non-breaking

### Gate 8: Tooling Impact — PASS

New `verify-artifacts` subcommand under `todo` follows existing subcommand pattern. `telec sync` handles command surface documentation updates.

---

## Plan-to-Requirement Fidelity

All implementation plan tasks trace to specific requirements:

| Requirement                    | Plan Tasks    | Fidelity                                                                              |
| ------------------------------ | ------------- | ------------------------------------------------------------------------------------- |
| R1: Direct peer conversation   | 2.1, 2.2, 2.3 | Plan correctly keeps reviewer alive, dispatches new fixer, establishes --direct links |
| R2: Artifact verification gate | 1.1, 1.2, 1.3 | Plan adds function, CLI, and state machine integration matching requirement spec      |
| R3: Session lifecycle wiring   | 3.1, 3.2      | Plan adds required read and strengthens POST_COMPLETION discipline                    |
| Validation                     | 4.1, 4.2      | Test coverage for verify_artifacts pass/fail cases                                    |

No contradictions detected between plan and requirements.

## Resolved Open Questions

1. **Review round counting during peer conversation:** Each REQUEST CHANGES transition increments `review_round` via `mark_phase`. The existing `max_review_rounds` safety cap applies naturally — the orchestrator checks `_is_review_round_limit_reached()` in the state machine.

2. **Fallback trigger for standard fix-review:** Falls back when no reviewer session ID is available (reviewer session died or was manually ended). The plan implements this as: standard fix-review dispatch is the state machine's default; peer conversation is orchestrated through POST_COMPLETION when a reviewer session is still alive.

## Assumptions (validated)

- Orchestrator manages session IDs in working memory via POST_COMPLETION instructions (not state.yaml). Confirmed: state.yaml schema has no session ID fields, and POST_COMPLETION instructions already use `<session_id>` placeholder.
- `telec sessions send --direct` is idempotent. Confirmed: CLI notes say "One-time ignition: sending once with --direct establishes/reuses the link."
- `session-lifecycle.md` exists as a resolvable doc snippet. Confirmed at `~/.teleclaude/docs/general/principle/session-lifecycle.md`.
