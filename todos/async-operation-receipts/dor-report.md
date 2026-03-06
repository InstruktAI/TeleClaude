# DOR Report: async-operation-receipts

## Gate Verdict: PASS (score 8)

This todo is ready for implementation provided the build remains tightly scoped to the
first adopter, `telec todo work`. The architecture is explicit, the recovery semantics are
resolved, and the key risk boundaries are already documented in the artifacts.

---

### Gate 1: Intent & Success — Pass

The problem statement is explicit: long-running routes are executing orchestration inside
HTTP request scope, causing slow-request warnings and client timeouts. The intended
outcome is concrete: make the API receipt-first and non-blocking while preserving simple
blocking CLI ergonomics through client-side polling. Success criteria are specific and
testable.

### Gate 2: Scope & Size — Pass

The change touches multiple layers, but it is still a single cohesive first-adopter
implementation:

- durable operation record
- submit/status contract
- worker execution lane
- `telec todo work` adoption
- CLI auto-wait + recovery

The artifacts already constrain the scope to one adopter and explicitly defer broader
route migration. That keeps the build atomic enough for a focused implementation session.

### Gate 3: Verification — Pass

Verification is concrete:

- submit dedupe tests
- single-claim execution tests
- `/todos/work` result compatibility tests
- stale-operation handling tests
- CLI recovery tests
- `make test`
- `make lint`

The resulting user-visible behavior is also observable end-to-end via receipt lookup and
operation progress inspection.

### Gate 4: Approach Known — Pass

The technical path is known:

- durable DB-backed state
- short-lived submit and status API calls
- background execution outside request scope
- CLI-side polling for blocking ergonomics
- caller-scoped reattachment for interrupted wrappers

The architecture distinction is resolved and documented: operation submission is
idempotent; `next_work()` itself is not.

### Gate 5: Research Complete — Pass (auto-satisfied)

No new third-party dependencies or external integrations are required. The work uses the
existing local TeleClaude stack: FastAPI, SQLite/DB layer, CLI, daemon background tasks,
and Next Machine.

### Gate 6: Dependencies & Preconditions — Pass

No prerequisite roadmap items block this todo. The required local components already
exist:

- `/todos/work`
- `next_work()`
- daemon background task infrastructure
- database/migration framework
- CLI tool surface

Caller identity requirements are already understood and documented.

### Gate 7: Integration Safety — Pass

The migration can be done incrementally:

1. add durable operation model
2. route `telec todo work` through it
3. keep current result semantics unchanged
4. postpone other slow-route adoption

Rollback is straightforward: revert the operation-backed route conversion if needed. The
scope is contained to one command in the first pass.

### Gate 8: Tooling Impact — Pass

The CLI behavior changes, but no scaffolding procedure or external developer workflow
needs to be redesigned. The command remains `telec todo work`; the transport semantics
change under the hood.

---

## Plan-to-Requirement Fidelity

The implementation plan traces cleanly to the requirements:

- operation storage and lifecycle ↔ durable receipt contract
- worker execution ↔ non-blocking API boundary
- `todo work` adoption ↔ first-adopter scope constraint
- recovery tasks ↔ explicit resubmit/reattach semantics
- test tasks ↔ success criteria and observability requirements

No contradictions remain in the current artifacts.

## Scope Notes

This item stays ready only if the build remains bounded to the documented first adopter.
If implementation expands to cover additional slow routes in the same session, the scope
should be reassessed.

## Blockers

None.
