---
adr_status: 'accepted'
date: '2026-06-11'
description: 'An ADR is one atomic, immutable reasoning report on the architecture decision timeline: it records a single decision, may reference only earlier decisions (never a later one), and never references work. This nature is sealed in the ADR authoring snippets and enforced as a review lane, not by a prose-grading validator.'
number: '31'
visibility: 'public'
---

# ADR-0031: ADRs Are Atomic Timeline Records — ADR

## Context

ADRs in this stack drifted into use as work and history scratchpads: records
cross-referenced each other — including forward, to decisions that did not yet
exist — carried `delivered_by` and named todos, and one cohesive contract was
sharded across several mutually-referencing records. The authoring snippets
stated immutability and the `supersedes` mechanism but never stated what an ADR
_is_, so agents inferred its nature and got it wrong, and reviewers had no rule to
check against. Inspecting ADR prose with a regex validator was considered and
rejected: judging whether a body references a later decision or work is a semantic
question, and `general/principle/intelligence-boundaries` reserves that judgment
for the agent reading it.

## Decision

An ADR is one atomic, immutable reasoning report on the architecture's decision
timeline — a single decision recorded at the moment it was made, looking only
backward. Three constraints are sealed in the authoring snippets and enforced at
review:

- One ADR records one decision. A cohesive contract whose parts must
  cross-reference is a spec or domain doc, not a set of mutually-referencing ADRs.
- An ADR may reference an earlier ADR; it may never reference a later one. The
  only forward link is `supersedes`, recorded on the newer ADR.
- An ADR records a decision, never work: no todo, slug, `delivered_by`, delivery,
  or TBD. It carries no `delivered_by` and has no companion file.

The rules live in `general/policy/adr-discipline` and the "What an ADR is" section
of `general/procedure/adr-authoring`, the structural notes in
`general/spec/snippet-authoring-schema`, and the `doc-hygiene` lane of
`software-development/policy/definition-of-done-lanes`, so both authors and
reviewers apply them. Numbering is unchanged — the number is the timeline
position and is correct.

## Consequences

Authors have an explicit definition to write against instead of inventing one, and
reviewers have a concrete contract to check on any `docs/project/adr/**` change: a
forward ADR reference or a work reference becomes a review finding. Existing
records are immutable and unchanged; this decision is forward-only and rewrites
nothing. Enforcement is reviewer judgment, not code — consistent with
`general/principle/intelligence-boundaries` and
`software-development/policy/no-semantic-validators` — so a body that smuggles a
forward or work reference past review remains possible; that is the accepted cost
of not building a prose grader.

## Alternatives Considered

- **A validator or lint that greps ADR bodies for ADR tokens, `delivered_by`, or
  slugs.** Rejected: regex on free text for a semantic decision is exactly the
  pattern `no-semantic-validators` forbids; the judgment belongs in the briefing
  and at review.
- **Drop ADR numbering for slug identity.** Rejected: numbering is the standard,
  correct timeline index; the problem was coupling and an undefined nature, not the
  digits.
- **Leave enforcement to authoring discipline alone.** Rejected: without a review
  lane the rule is invisible to reviewers and recurs — the failure that produced
  this decision.
