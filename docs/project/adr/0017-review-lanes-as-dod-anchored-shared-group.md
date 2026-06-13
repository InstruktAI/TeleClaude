---
date: '2026-06-07'
description: 'Review lanes are extracted into one DoD-anchored shared catalog that the build reviewer, commit reviewer, and planner all reference, instead of being embedded in the build-review procedure and re-described in the plan reviewer.'
number: '17'
visibility: 'public'
---

# Review Lanes as a DoD-Anchored Shared Group — ADR

## Context

The review lanes (scope, code, security, tests, docs, …) were defined inside the
build-review procedure (`work/review.md`) and **re-described** in the plan
reviewer (`prepare/review-plan.md`). The commit reviewer (`work/review-commits.md`)
already reused `review.md`. So two reviewers shared one copy and a third forked it:
the lane set could drift between "what the plan anticipates" and "what build-review
checks," and the lanes were not a first-class unit any agent could point at.

This surfaced when the doc-snippet-reflection gate was added at plan-review (ADR
0015 obligation): there was no single home to also give build-review and
commit-review the same doc-reflection catch — the docs lane lived only inside
`review.md` and would have needed duplicating into the commit-review path.

## Decision

The lanes are the **review-time enforcement of the Definition of Done**. Extract
them into one shared catalog, `software-development/policy/definition-of-done-lanes`
(`type: concept`), co-located with the DoD gates they enforce.

- **Option B (uniform):** the catalog holds **all** lanes, and each lane names its
  own **Authority** — a DoD section, the requirement contract (`prd`/`input`) for
  the scope lane, or a design principle. One home; honest per-lane citation.
- **Consumers reference, never re-describe:** `work/review` executes the lanes,
  `work/review-commits` executes them minus scope, and `prepare/plan-draft` +
  `prepare/review-plan` anticipate them. All four point at the catalog.
- **Execution mechanics stay in `work/review`:** the lane execution gate, severity
  schema, citation rules, and verdict arithmetic are how a review is _run_, not
  what each lane _checks_ — they remain in the review procedure.
- **The docs lane gains the doc-snippet reflection catch** once, in the catalog,
  so build-review and commit-review inherit it as a backstop to the plan-review
  documentation hard gate.

Structure: the catalog is the sibling file `policy/definition-of-done-lanes.md`,
next to `policy/definition-of-done.md` (which keeps its id
`software-development/policy/definition-of-done`). It is a separate snippet so
reviewers `@`-include the lanes as a unit without pulling in the gate checklist.

## Consequences

- One definition of each lane; the plan-anticipation/build-execution drift is
  structurally removed because there is a single source.
- The DoD↔lane coupling is explicit: a new DoD gate should grow a lane; a lane
  must name the gate it answers to (its Authority line).
- `work/review` shrinks to review flow + verdict machinery; ~290 lines of lane
  detail moved verbatim to the catalog (lane bodies unchanged, each gained an
  Authority line; the docs lane gained the snippet-reflection catch).
- The conditional `doc-first paradigm check` and `bug-fix` checks move into the
  catalog as conditional lanes.
- Reviewers load the catalog via Required reads; the planner references it when
  anticipating lanes.

## Alternatives Considered

- **Do #1 (broaden docs lane in `review.md`) and #2 (de-dup `review-plan`) first,
  then extract:** rejected — throwaway work, since extraction relocates the same
  text; the extraction subsumes both.
- **Convert `definition-of-done.md` to `definition-of-done/overview.md`:**
  rejected — it changes the DoD id and forces updating ≈12 references for no gain
  over the file+subfolder layout.
- **A standalone `review/lanes/` group not tied to DoD:** rejected — it loses the
  point that lanes _are_ the DoD's review-time enforcement; anchoring under DoD
  keeps gate and check from drifting apart.
- **Split each lane into its own file under `lanes/`:** rejected for now —
  over-fragmentation; one catalog snippet is the minimal DRY fix. A later split is
  possible if lanes need independent addressing.
