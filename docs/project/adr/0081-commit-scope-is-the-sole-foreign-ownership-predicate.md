---
visibility: public
number: 0081
date: 2026-09-08
description: Conventional-commit scope is the only predicate that parks a candidate for foreign ownership; a touched path outside the plan's referenced-paths contract becomes ambiguity evidence instead.
---

# Commit Scope Is the Sole Foreign-Ownership Predicate — ADR

## Context

ADR-0076 decided that a candidate whose commit span is mechanically proven to
carry another live slug's work is parked, while ambiguous provenance is surfaced
to the integrator for judgment. Two predicates were built to supply that proof: a
conventional-commit scope naming another active slug, and a touched path falling
outside the candidate's frozen implementation-plan referenced-paths contract.

The path predicate does not establish what it was built to establish. A plan's
referenced-paths contract is frozen at prepare hydration, before the build runs.
Two ordinary and correct events therefore breach it:

- The build extracts a new module. The file is agent-owned HOW inside the
  candidate's own slug, and no plan could have named it.
- A sibling todo delivers a file to `origin/main`, the candidate merges main, and
  that sibling's own delivered contract obliges the candidate to adapt to it. The
  file did not exist when the plan froze.

Neither is another slug's work. Both are indistinguishable, under the path
predicate, from the contamination the gate exists to catch. Because the breach is
structural rather than incidental, the verdict is also unrecoverable: the frozen
contract cannot grow, so every subsequent drain reproduces the same park.

Observed cost: two finalize-ready candidates parked across three consecutive
drains, both on paths their own builds or a delivered sibling created, with no
role able to advance them.

The scope predicate is unaffected. A commit carries its slug scope, so genuine
cross-slug contamination arrives already labelled.

## Decision

Conventional-commit scope is the only predicate that yields a FOREIGN verdict.

- A span commit whose scope names a different active slug is foreign and parks
  the candidate, unchanged from ADR-0076.
- A span commit whose scope is the candidate's own slug is clean, whatever paths
  it touches. The slug owns its commits; new modules are agent-owned HOW.
- A span commit whose header attributes it to no registered slug remains
  ambiguous and is surfaced to the integrator's judgment. Where such a commit
  also breaches the referenced-paths contract, that breach is carried as the
  ambiguity's reason so the integrator sees why the commit looks unattributed.

A referenced-paths breach never parks a candidate and never, on its own, raises a
question for the integrator.

## Consequences

- A candidate that extracts a module, or adapts to a sibling's delivered file, is
  no longer parked for doing so, and the unrecoverable park class disappears with
  the predicate that produced it.
- Cross-slug contamination is still parked on the predicate that actually proves
  it, so ADR-0076's gate strength against real foreign work is retained.
- Plan-versus-build path divergence stops being reported as an ownership verdict.
  It is a preparation-fidelity concern owned by build review, which reads the
  diff against the plan directly.
- The integrator is prompted only on commits that are genuinely unattributed,
  keeping the ambiguity surface rare enough to stay worth reading.
- A commit mislabelled with the candidate's own scope while carrying another
  slug's work now passes cleanly. This was already true in practice: the path
  predicate could not separate that case from a legitimate new module, so it
  guessed rather than proved.

## Alternatives Considered

- **Give a FOREIGN path verdict the accept-or-park instruction AMBIGUOUS already
  gets.** Rejected. It routes a predicate whose positives are overwhelmingly
  false to the integrator, which would prompt on nearly every candidate that
  created a file. The integrator would learn to accept reflexively, degrading the
  ambiguity surface that works today, and the underlying conflation of divergence
  with ownership would survive intact.
- **Refresh referenced-paths from the build before inspection.** Rejected. It
  makes the candidate's own later commits define the contract they are then
  measured against, which is not a gate. It also cannot be authored honestly at
  plan time, leaving the freeze semantics that drift detection depends on.

## Status

Superseded in full by ADR-0082: span-ownership inspection is withdrawn entire, so
the predicate this record narrowed no longer exists.
