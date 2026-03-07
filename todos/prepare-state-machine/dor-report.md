# DOR Assessment: prepare-state-machine

**Assessed at:** 2026-03-07T13:15:00+00:00
**Score:** 9 / 10
**Verdict:** PASS

---

## Gate 1: Intent & Success (PASS)

The input.md states the problem clearly: `next_prepare()` is a linear if/else chain
that needs to become a deterministic state machine with durable checkpoints. The
intended outcome is explicit -- 10-state PreparePhase enum, crash-recoverable
checkpoints in state.yaml, event emission at transitions, hitl removal, CLI
invalidation flag, and pre-build freshness gate.

Requirements.md translates this into 10 concrete requirements (R1-R10) with
per-requirement verification criteria. The success criteria section in requirements.md
lists 10 testable conditions. All are concrete and mechanically verifiable (enum
existence, grep zero-occurrence, round-trip tests, CLI flag checks).

No ambiguity in what "done" looks like.

## Gate 2: Scope & Size (PASS)

Ten tasks, each commit-worthy. The implementation plan estimates this as a single
AI session. The largest tasks (Task 10: test rewrite, Task 9: CLI changes) are
well-scoped with explicit file lists. The plan explicitly defers review command
implementations, triangulation procedure, and work-phase state machine as out of
scope.

The total touch surface is:
- 1 core file (core.py) for the state machine
- 3 CLI/API files (telec.py, tool_commands.py, todo_routes.py) for hitl removal and new flags
- 1 event file (software_development.py) read-only verification
- 3 test files (2 rewrites, 1 new)

This fits a focused session. Risk of context exhaustion is low given the clear
task ordering and the fact that most handlers follow the same structural pattern.

## Gate 3: Verification (PASS)

Every requirement has explicit verification criteria:
- R1: Enum existence unit test
- R2: Dispatcher compilation test, loop-limit test
- R3: Round-trip test, backward compatibility test
- R4: Per-transition-edge unit tests (table in requirements)
- R5: Mocked EventProducer tests
- R6: Tool-call assertion tests
- R7: Mocked git operation tests (fresh + stale scenarios)
- R8: CLI flag test, invalidation/non-invalidation tests
- R9: Integration test (stale grounding blocks build)
- R10: Grep zero-occurrence test across all code paths

The demo.md provides 7 validation bash blocks covering enum verification, hitl
removal, DEFAULT_STATE extension, backward compatibility, CLI help flags, unit
tests, and full regression. The guided presentation adds 5 interactive steps
demonstrating the state machine in action.

Verification chain is complete: unit tests (per handler) -> integration tests
(pre-build gate) -> demo (end-to-end observable behavior) -> grep (contract
verification).

## Gate 4: Approach Known (PASS)

The approach is explicitly modeled on the existing integration state machine
(`state_machine.py`). The plan references specific line ranges in the source:

- Enum placement: core.py lines 42-74 (verified -- PhaseName, PhaseStatus, ItemPhase are there)
- DEFAULT_STATE: core.py lines 799-810 (verified -- exact location)
- Step dispatcher: state_machine.py lines 603-702 (verified -- `_step()` function)
- Current next_prepare: core.py lines 2406-2577 (verified -- function starts at 2406)
- Event schemas: software_development.py lines 194-300 (verified -- all 10 prepare events registered)
- CLI hitl: telec.py lines 519, 1092; tool_commands.py lines 736-774 (verified)
- API hitl: todo_routes.py lines 51-66 (verified)

The plan's F2 builder note about shallow merge in DEFAULT_STATE is a concrete
mitigation for a real risk (partial grounding sections losing sub-keys). The F4
builder note about prepare_phase vs grounding.valid for legacy todos is another
correct mitigation.

No unknowns. The pattern is proven and the references are accurate.

## Gate 5: Research Complete (PASS)

No third-party dependencies introduced. The implementation uses only existing
stdlib (hashlib, subprocess, enum) and project-internal patterns. All 10 prepare
event types are already registered in software_development.py. The integration
state machine pattern is an internal, proven pattern.

Auto-pass on third-party research. Internal dependencies are fully mapped.

## Gate 6: Dependencies & Preconditions (PASS)

Prerequisites are listed in the input:
- Integration state machine pattern (exists at state_machine.py)
- Event schemas registered (verified -- 10 prepare events in software_development.py)
- Existing state.yaml I/O (read_phase_state/write_phase_state at core.py:818-858)
- Existing format_tool_call infrastructure
- Existing DOR_READY_THRESHOLD constant (core.py:61)

The grounding section in state.yaml is already populated (state.yaml shows
grounding with valid=true, base_sha, referenced_paths). The requirements_review
and plan_review sections are also already present in state.yaml. This means the
state schema extension is already partially in use for this todo itself.

No external configs, no access requirements, no service dependencies.

## Gate 7: Integration Safety (PASS)

The plan is designed for incremental merging:
- Task 1 (enum) is additive -- no existing code changed
- Task 2 (DEFAULT_STATE extension) is additive -- shallow merge means old state
  files still load correctly
- Task 3 (dispatcher skeleton with stubs) replaces the function body but with
  the same external contract (minus hitl)
- Tasks 4-8 fill in stub handlers incrementally
- Task 9 (CLI/API changes) removes hitl from all call sites simultaneously
- Task 10 (tests + pre-build gate) is the final integration

The hitl removal (Task 3 signature + Task 9 callers) must happen atomically or
the build breaks between commits. The plan handles this: Task 3 removes hitl from
the function signature, and Task 9 removes it from all callers. If committed
separately, there is a window where callers pass hitl but the function does not
accept it.

**Minor concern:** Tasks 3 and 9 together constitute the hitl removal. If the
builder commits Task 3 before Task 9, the intermediate commit breaks compilation.
However, the plan says Task 3 removes hitl from the signature, and the existing
callers will fail at import time. The builder should be aware this needs to land
together or the callers need a compatibility shim. The plan's Task 9 "Why" section
acknowledges: "The hitl removal must touch all call sites simultaneously."

This is an informational note for the builder, not a blocker. The plan is aware
of the constraint.

## Gate 8: Tooling Impact (PASS)

The CLI surface changes:
- Removes `--no-hitl` flag from `telec todo prepare`
- Adds `--invalidate-check` and `--changed-paths` flags

Task 9 explicitly lists the CLI_SURFACE dict update, completions allowlist update,
and help text changes. The demo.md validates the CLI help output.

No scaffolding procedure changes needed -- `telec todo prepare` is a workflow
command, not a scaffolding command. The `telec todo create` scaffolding is
unaffected.

---

## Cross-Artifact Validation

### Every plan task traces to a requirement

| Task | Covers |
|------|--------|
| Task 1 | R1 |
| Task 2 | R3 |
| Task 3 | R2, R10 |
| Task 4 | R2, R4 |
| Task 5 | R4, R6 |
| Task 6 | R4, R6 |
| Task 7 | R4, R7 |
| Task 8 | R5 |
| Task 9 | R8, R10 |
| Task 10 | R2, R4, R9, R10 |

All 10 tasks map to at least one requirement. No orphan tasks.

### Every requirement has at least one plan task

| Requirement | Task(s) |
|-------------|---------|
| R1 | Task 1 |
| R2 | Tasks 3, 4, 5, 6, 7, 10 |
| R3 | Task 2 |
| R4 | Tasks 4, 5, 6, 7, 10 |
| R5 | Task 8 |
| R6 | Tasks 5, 6 |
| R7 | Task 7 |
| R8 | Task 9 |
| R9 | Task 10a |
| R10 | Tasks 3, 9, 10b |

All 10 requirements have plan coverage. No orphan requirements.

### Verification chain satisfies DoD gates

- **Unit tests:** Per-handler tests (Tasks 4-8), enum tests (Task 1), state I/O
  tests (Task 2), invalidation tests (Task 9)
- **Integration tests:** Pre-build freshness gate (Task 10a)
- **Regression:** Full `make test` + `make lint` (Task 10b)
- **Demo:** 7 validation blocks + 5 guided presentation steps (demo.md)
- **Contract verification:** Grep for hitl zero-occurrence (Task 10b)

The DoD gates (tests pass, lint clean, demo validates, no regressions) are all
addressed.

---

## Deductions

**-1 point: Atomic hitl removal across commits.** Tasks 3 and 9 create a compile-breaking
window if committed separately. The plan acknowledges this risk but does not
explicitly prescribe a single-commit strategy or compatibility shim for the
intermediate state. The builder must understand this constraint. This is a minor
coordination risk, not a blocker -- it is flagged in the plan's Task 9 "Why"
section and in the review's F4 finding.

---

## Final Score: 9 / 10

All 8 gates pass. The artifacts are thorough, well-cross-referenced, and grounded
in verified codebase references. The single deduction is for a coordination nuance
in the hitl removal sequence that the builder must handle carefully but that is
already flagged in the artifacts.

**Verdict: PASS** -- ready for build.
