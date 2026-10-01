---
date: 2026-06-14
description: The bug DIAGNOSE phase grounds the root cause and prescribes no fix; evidence and conclusion become separate artifacts. Reverses ADR 0019's fix-prescription clause.
number: 48
visibility: public
---

# Diagnosis Records Cause, Not Fix — ADR

## Context

ADR `0019-bug-lane-diagnosis-gate` established the mandatory bug `DIAGNOSE` gate but
had the phase **prescribe** the fix approach and a verification approach inside the
`diagnosis` artifact. In practice that prescription is the seam through which
symptom-masking workarounds — fallbacks, default substitutions, broad catches — enter
the bug lane: a phase permitted to propose the fix optimises for the cheapest change
that quiets the symptom, because its objective has shifted from _understand_ to
_alleviate_. An objective of alleviation does not reliably reach cause.

Two structural facts compounded it. The conclusion and the evidence it rests on lived
in one artifact, so a restatement of the symptom could pass as a grounded conclusion.
And the "investigated but could not ground a cause" state had no representation — it was
an absence. Separately, 0019 rejected a "standalone analysis artifact," but it rejected
one carrying a _bespoke fix prescription_, conflating an evidence substrate with a fix
plan.

## Decision

The `DIAGNOSE` phase grounds the root cause and prescribes no fix; the planner owns the
fix that removes the cause. The lane's sensemaking is split into two concerns — the
evidence gathered and the conclusion drawn from it — so the conclusion is auditable
against its evidence and the "no cause grounded" state is representable rather than an
absence.

This supersedes 0019's clause that the `DIAGNOSE` phase prescribes the fix and
verification approach, and narrows 0019's rejection of an analysis artifact to artifacts
that carry a fix prescription. The shape of the two artifacts, and the behaviour when a
cause will not ground, live in the diagnose procedure — not in this record.

## Consequences

- The fix is reviewed as a decision at plan-review, not inherited as a prescription
  riding the diagnosis's authority. A bug's fix decision gets the scrutiny any decision
  with alternatives deserves.
- An ungrounded cause has a defined, honest path instead of a fabricated conclusion: the
  phase stops and escalates rather than advancing a "likely" cause.
- 0019's downstream pipeline is unchanged — bugs still run `diagnosis` →
  `PLAN_DRAFTING` → `PLAN_REVIEW`, the diagnosis is still validated in one plan-review
  pass with no separate diagnosis-review, and the planner still consumes the diagnosis
  with no kind-branching. Only what the diagnosis contains, and that it prescribes
  nothing, changes.

## Alternatives Considered

- **Keep 0019's prescribing diagnosis, tighten the wording only.** Rejected: the
  prescription itself is the seam, and wording cannot close a hole the structure opens.
- **Keep evidence and conclusion bundled in one `diagnosis` artifact.** Rejected:
  bundling lets a symptom restatement pass as a grounded conclusion and leaves the
  blocked state invisible — the two failures this decision corrects.
