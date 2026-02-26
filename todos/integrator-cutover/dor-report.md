# DOR Report: integrator-cutover

## Gate Verdict

**Score:** 8/10
**Status:** pass
**Assessed:** 2026-02-26T16:10:00Z

All 8 DOR gates satisfied. This todo is ready for build once predecessor
slices (`integration-events-model`, `integrator-shadow-mode`) are delivered.

---

## Gate-by-Gate Assessment

### Gate 1: Intent & Success — PASS

Problem statement is explicit: remove non-integrator canonical write authority
and make the singleton integrator the only merge/push path for `main`. Eight
success criteria are concrete and independently testable.

### Gate 2: Scope & Size — PASS

Atomic slice covering authority cutover only. Out-of-scope items are explicit
(blocked-flow UX, event schema redesign, non-integration workflows).
Cross-cutting touches called out: next-machine finalize contract, integrator
runtime, config, docs, tests.

### Gate 3: Verification — PASS

Verification path covers four layers:

1. Unit/integration tests for finalize retirement and integrator apply paths.
2. Regression tests for safety gates at the apply boundary.
3. Static checks confirming legacy canonical push commands are absent.
4. Operational log checks via `instrukt-ai-logs`.

Error paths (conflict, precondition failure, containment pause) are explicit
in both requirements and plan.

### Gate 4: Approach Known — PASS

Approach grounded in three existing contracts:

1. `docs/project/spec/integration-orchestrator.md` — authority/lease/queue model.
2. Finalize post-completion contract in `teleclaude/core/next_machine/core.py`.
3. Shadow-mode runtime primitives from predecessor slice.

No unresolved architectural decisions. Open implementation details (config key
naming, operator runbook wording) are build-time concerns.

### Gate 5: Research Complete — PASS (auto)

No new third-party tooling or integrations introduced.

### Gate 6: Dependencies & Preconditions — PASS

Dependency chain correctly encoded in `roadmap.yaml`:
`integration-safety-gates` (delivered) →
`integration-events-model` (DOR pass, build pending) →
`integrator-shadow-mode` (DOR pass, build pending) →
`integrator-cutover`.

Daemon availability and single-database policy captured as preconditions.

### Gate 7: Integration Safety — PASS

Cutover controlled by explicit mode/config with:

- Containment pause preserving queue integrity.
- All-or-nothing per-candidate semantics (no partial push).
- Explicit entry/exit boundaries.

### Gate 8: Tooling Impact — PASS (auto)

No scaffolding or tooling pipeline changes required.

---

## Plan-to-Requirement Fidelity

All 10 implementation tasks trace to requirements R1–R8:

| Task                                     | Requirements   | Verified |
| ---------------------------------------- | -------------- | -------- |
| 1.1 Cutover mode + operator control      | R1, R7         | Yes      |
| 1.2 Retire legacy finalize apply         | R1, R2, R8     | Yes      |
| 1.3 Write-capable integrator apply       | R1, R3, R5, R6 | Yes      |
| 2.1 Safety checks at integrator boundary | R4, R5, R8     | Yes      |
| 2.2 Blocked-path persistence             | R5, R6         | Yes      |
| 2.3 Pause/resume containment             | R7, R6         | Yes      |
| 3.1 Tests                                | R1–R5, R7, R8  | Yes      |
| 3.2 Operational verification             | R6, R7, R8     | Yes      |
| 3.3 Quality checks                       | R8             | Yes      |
| 4.0 Review readiness                     | R8             | Yes      |

No task contradicts any requirement. The plan extends shadow-mode primitives
rather than reimplementing them, consistent with the dependency model.

---

## Codebase Verification

Gate assessment included codebase inspection:

- `teleclaude/core/next_machine/core.py` contains `FINALIZE_READY` signal,
  canonical main safety checks, and `git merge` patterns — confirming the
  legacy apply path the plan targets for retirement.
- `docs/project/spec/integration-orchestrator.md` exists with complete
  authority/lease/queue model matching plan assumptions.
- No integrator runtime modules exist yet in `teleclaude/core/` — expected,
  as these are delivered by `integrator-shadow-mode`.
- `teleclaude/config.py` does not exist yet — expected from predecessor
  delivery; not a plan contradiction.
- No integration-related DB models exist yet — expected from predecessor
  delivery.

---

## Assumptions (Validated)

1. `integrator-shadow-mode` delivers durable queue/lease runtime primitives
   that cutover extends rather than reimplements. _(Confirmed: shadow-mode DOR
   pass, plan references extension not reimplementation.)_
2. `integration-events-model` readiness projection remains the canonical source
   for enqueue eligibility. _(Confirmed: events-model DOR pass, spec defines
   readiness predicate.)_
3. Integrator cutover writes remain within canonical single-DB and daemon
   policy constraints. _(Confirmed: requirements explicitly reference these
   policies.)_

## Open Items (Non-blocking)

1. Config key naming for shadow/cutover/containment modes — implementation
   detail, resolved at build time.
2. Operator runbook wording for pause/resume during active queue drain —
   implementation detail, resolved at build time.

## Actions Taken (Gate)

1. Validated all 8 DOR gates against artifacts and codebase state.
2. Verified plan-to-requirement fidelity with traceability matrix.
3. Confirmed codebase state matches plan assumptions via code inspection.
4. Promoted gate verdict from `needs_work` to `pass` at score 8.
