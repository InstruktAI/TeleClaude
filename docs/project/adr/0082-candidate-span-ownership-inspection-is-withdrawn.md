---
visibility: public
number: 0082
date: 2026-09-08
description: Span-ownership inspection is removed from the integrator; the contamination it guarded against is prevented by worktree isolation and was never observed.
---

# Candidate Span-Ownership Inspection Is Withdrawn — ADR

## Context

ADR-0065 established park-and-drain from observed operational failure: a
containment probe wedging in a push loop, and one undeliverable candidate
starving every independent delivery behind it. Both were measured.

ADR-0076 restated that decision and named three park causes in one sentence —
textual conflict, foreign work, gate failure. Two of the three carried the
evidence ADR-0065 had gathered. The third did not. No observation of a
candidate carrying another slug's commit was recorded, then or since, and the
mechanism by which one could arise was never established.

Span-ownership inspection was built on that clause and shipped on 2026-09-07.
Its exact predicates — a conventional-commit scope naming another active slug,
or a touched path outside the frozen implementation-plan referenced-paths
contract — were stated as mechanics rather than derived from a case.

The path predicate immediately produced false positives, because a plan's
referenced-paths contract freezes before the build while `origin/main` keeps
moving during it. Two finalize-ready candidates parked across three drains on
paths their own builds created or a sibling's delivery obliged them to touch.
ADR-0081 narrowed the predicate to scope alone, which cleared those two
candidates and left the scope half standing on its original unmeasured premise.

Measurement then established the premise is false. Across 61 live branches and
239 span commits, no commit carries a conventional-commit scope naming a
different active slug. The architecture prevents it: every slug branch is
created from `origin/main` and never from another branch, each job builds in its
own worktree so its directory determines its branch, and agents cannot invoke
raw Git to transplant a commit. There is no path by which the condition arises.

What remained after ADR-0081 was therefore a check whose foreign verdict is
unreachable and whose ambiguous verdict fires on commit-message style — a scope
naming a component rather than a registered slug — and interrupts the integrator
for a judgment no ownership question underlies.

## Decision

Span-ownership inspection is removed from the integration state machine.

- The integrator performs no cleanliness classification of a candidate's span.
  Every finalize-ready candidate proceeds to its squash merge on its dependency
  order alone.
- The `candidate_cleanliness` park reason, the ownership-ambiguity prompt shown
  in the commit and conflict instructions, and the ambiguity evidence carried
  through checkpoint `error_context` are withdrawn with it.
- Park-and-drain itself is unchanged. Textual-conflict parking and
  ungroundable-content-gate parking keep their evidence and their behaviour, and
  the pre-push quality gate remains authoritative and blocking.
- ADR-0081 is superseded in full: it corrected one half of a mechanism that is
  withdrawn entire.

## Consequences

- Both parked candidates deliver on their dependency order, including the one
  ADR-0081 left routed to integrator judgment.
- The integrator runs two fewer Git traversals per candidate and can no longer
  interrupt a drain over commit-message scope spelling.
- A commit genuinely belonging to another slug, were one ever to reach a branch,
  would now be squash-merged with its host. The measurement above is what makes
  that acceptable, and it is falsifiable: were such a commit ever observed, this
  decision is the record to revisit, and the reasoning would restart from the
  observation rather than from an asserted risk.
- Conventional-commit scope keeps its documentary value and loses its gate role.

## Alternatives Considered

- **Keep the scope predicate as cheap insurance.** Rejected. Its cost is not the
  two Git calls but the standing it lends an unmeasured premise: a live check
  reads as evidence that the risk is real, and the next agent to touch this area
  inherits that reading rather than the measurement.
- **Keep the ambiguity prompt as a commit-message convention check.** Rejected.
  Convention belongs to authoring and review, not to an integrator that has no
  authority over how a commit was worded and cannot fix it.

## Status

Accepted.
