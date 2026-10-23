---
description: 'Top-level software development lifecycle design: the item body as the spec, a coordinating driver, producer child and dedicated reviewer per phase, the rigor model, and phase boundaries.'
visibility: 'public'
---

# SDLC Overview — Design

## Required reads

- @~/.teleclaude/docs/sdlc/principle/externalized-structural-context.md

## Purpose

Define the top-level software development lifecycle used by the platform.

This design is intentionally above machine implementation details. It defines:

- the phase boundaries of the lifecycle
- the authority of the item's spec and the contracts it references
- the sequential roles in each phase: a producer child, an independent reviewer child and a coordinating driver
- the split between automation and judgment

The lifecycle is designed for autonomy without losing rigor.

## Inputs/Outputs

**Inputs**

- the intent an item carries in its body, from a single line to a worked proposal
- current codebase and system reality
- computed supporting context where automation can provide it

**Outputs**

- a prepared spec in the item's body, with its durable contract changes in reviewed pending snippets
- an implemented change, stamped at the commit that is ready
- an integrated change on the shared branch

## Invariants

- The item's body is the spec. Preparation writes it; work builds against the
  body revision preparation judged ready, and a body that has moved since is
  not built.
- Each phase separates completed production from review. The author or builder
  works independently, then a dedicated reviewer assesses the completed target.
  The driver coordinates and arbitrates scope and procedure without substituting
  its own technical approval; compromised reviewer independence requires
  an unprimed reviewer (`sdlc/procedure/lifecycle/review`).
- Durable contract changes are authored doc-first, in pending snippets that are
  independently reviewed before the work that depends on them is built.
- Automation computes what can be computed so judgment can focus on
  interpretation, trade-offs, and decisions; it never grades the judgment.
- Structural context is an SDLC input where available; it does not replace
  judgment.
- A person takes part by dropping in at any time, and is waited on only for a
  fork that is genuinely theirs to decide.
- AI performs most spec and code work, but only inside explicit contract and
  process boundaries.

## Primary flows

### Prepare

Preparation turns the intent in an item's body into a fleshed-out spec in that
body (`sdlc/design/lifecycle/prepare`). The author completes the specification
and pending contracts, preserving independent review of each coherent doc
commit. A dedicated reviewer assesses the complete specification before the
driver records readiness at the approved body revision.

Rigor is preserved by:

- deriving the smallest complete outcome independently before judging a draft
- grounding the delivery in the existing path for comparable outcomes
- challenging unnecessary complexity as well as missing behavior
- establishing a bug's cause with evidence before it is prepared
- binding readiness to an exact body revision

### Work

Work realizes the prepared spec in code (`sdlc/design/lifecycle/work`). The
builder completes each coherent commit before a dedicated reviewer assesses it.
After all units, final review executes the lanes against the resulting whole
delta. The driver records readiness at that reviewed integration head after
sequential remediation closes valid findings.

Rigor is preserved by:

- building against the prepared spec at its revision
- reviewing each completed coherent commit and then the resulting whole delta
- executing every applicable review lane before the stamp, with no blocking
  finding left unresolved
- returning the item to preparation when the spec itself is wrong

### Integration

Integration turns locally valid changes into globally safe system truth under
concurrent delivery (`sdlc/design/lifecycle/integration`). It takes a ready
item as a candidate at its stamped commit.

Rigor is preserved by:

- considering queue context and overlap before landing
- making sequencing explicit instead of accidental
- validating cutover safety and post-landing system coherence

### Shared rigor model

The lifecycle preserves rigor by combining:

- an explicit spec and explicit contract authority
- a dedicated judge with no delivery stake, authorship or co-design of its target
- findings and readiness bound to exact revisions and commits
- aggressive supporting automation that computes facts for judgment

### Persistent quality focus points

These are continuous pressures across the lifecycle, not isolated later phases:

- correctness
- security
- maintainability
- performance
- observability
- operability
- simplicity
- integration fit
- product fidelity

## Failure modes

- The spec grows mechanisms the authorized outcome does not need because the
  reviewer judged only the details, not the whole delivery.
- Work builds against a body that moved after it was judged ready.
- Review checks only local correctness and ignores the spec or its contracts.
- A contract change discovered during work is coded before it is authored and
  reviewed as pending documentation.
- Integration is treated as “merge after approval” instead of concurrency-safe
  system convergence.
- Structural context is unavailable or ignored, causing grep-driven planning,
  duplicated paths, zombie code, and hidden impact.

## See Also

- ~/.teleclaude/docs/sdlc/procedure/lifecycle/overview.md —
  operational steps for executing this lifecycle
