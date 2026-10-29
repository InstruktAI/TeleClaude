---
visibility: public
number: 0150
date: 2026-10-29
description: While a todo's lifecycle phase is one of the work lane's, its prepare artifacts are writable by no caller, the work orchestrator and a direct human-identity writer included; kickback through the work orchestrator reopens the contract.
---

# Prepare artifacts close while their contract is under execution — ADR

## Context

ADR-0067 made workflow authorization the conjunction of capability, ownership
and phase, and stated that a contract under execution is closed to mutation
whatever the caller is. The phase condition was never built for the prepare
artifacts. What stood in for it was the prepare-author role list: by refusing
the work orchestrator at every phase, it kept the session holding a todo during
its build from changing the plan the builder executes, while the human and
roleless writers stayed free to do so.

ADR-0149 replaced that list with the role catalog's `prepare-artifact-write`
capability. The work orchestrator is full-reach, so it reaches the capability,
and ADR-0149 left the phase condition as a separate decision, relying on the
work lane's brief to keep the work orchestrator out of the prepare artifacts
during a build.

The lifecycle phase records whether a contract is under execution:
`WORK_LIFECYCLE_PHASES`, from build started through finalize ready, is already
the work-lane boundary that readiness and slug resolution read. Kickback, the
work lane's way back to preparation, writes its record into `input` through the
workflow's own store rather than through the artifact write boundary, and the
prepare lane's next call persists the derived phase, which leaves the work lane.

## Decision

While a todo's lifecycle phase is one of the work lane's, its prepare artifacts
— `input`, `prd`, `architecture`, `diagnosis` and `implementation-plan` — are
writable by no caller through the artifact write boundary, whatever its role or
reach, a direct human-identity writer included. The refusal names the phase and
the door: the todo's work orchestrator returns it to preparation through
kickback, and the prepare lane's next call reopens the contract.

The claim gate keeps deciding first; the closed-contract refusal follows, then
the capability refusal of ADR-0149.

## Consequences

- The work orchestrator, and every other caller, is kept from changing the plan
  under the build by a fact about the todo rather than by a name.
- A direct human-identity writer and a roleless session can no longer edit a
  prepare artifact during a build; they reach the work lane, whose orchestrator
  kicks the todo back. This is the narrowing ADR-0067 accepted.
- Kickback stays available, because it writes through the workflow's store;
  the closure governs the caller-facing boundary only.
- `PREPARED`, the prepare phases and the task lane stay open: a contract that is
  approved but not executing is protected by digest-bound review invalidation,
  not by closure.
- A prepare-artifact write reads the todo's state once more than before.

## Alternatives Considered

- **Leave the work phase to the work lane's brief, as ADR-0149 did.** Rejected:
  the brief binds only the work orchestrator, while a human-identity or roleless
  writer and every full-reach session remain free to change a plan during its
  build. The harm is a contract changed underneath the party executing it, which
  restoring the artifact's earlier version does not repair.
- **Refuse the work orchestrator by name.** Rejected: it protects the build from
  one caller, reads the caller instead of the todo, and restores the role list
  ADR-0149 removed.
- **Close the prepare artifacts from `PREPARED` onwards.** Rejected: a prepared
  todo is not yet executing, and a prepare-lane refinement after approval is an
  ordinary act that re-runs the affected review.
