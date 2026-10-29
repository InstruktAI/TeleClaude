---
description: 'Architecture review phase. Validate the architecture artifact against the approved PRD, project architecture, codebase reality, and platform defaults.'
visibility: 'public'
role: architecture-reviewer
parameters:
  - name: slug
    required: true
dispatch:
  agent: [codex, claude, gemini, deepseek]
  thinking_mode: slow
---

# Review Architecture — Procedure

## Required reads

- @~/.teleclaude/docs/sdlc/principle/design-fundamentals.md

- @~/.teleclaude/docs/sdlc/principle/architectural-defaults.md
- @~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/sdlc/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/sdlc/policy/state-storage.md
- @~/.teleclaude/docs/sdlc/procedure/lifecycle/work/review-build.md

## Goal

Validate that the architecture preserves the independently reviewed and
human-approved target while reconciling it with current code, credible intended
state, relevant solution evidence, and platform defaults. Reject both
unsupported invention and status-quo absorption.

## Preconditions

- `telec todo artifacts read {slug} prd` exists and is approved.
- `telec todo artifacts read {slug} architecture` exists.
- Slug is active and not delivered.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

First read the sdlc principles as listed in the sdlc baseline that apply to this work with `telec docs get`.

### 1. Read context

- Apply the artifact-discovery rule from `preparation-artifact-quality`
  (`telec todo artifacts list {slug}`) — read `log` when present, and any
  other present artifact relevant to this review.
- `telec todo artifacts read {slug} prd` — the approved product contract.
- From the PRD and the code alone, before any design material, name the
  nearest existing in-system path that does the same job and the primitives
  the work's external systems offer for it, read from their current
  documentation (`sdlc/procedure/lifecycle/prepare/architecture`, step 1a).
  This is the baseline step 3 judges the design against.
- In the same pass, before any design material, classify each piece of
  durable state the PRD's outcomes require under `sdlc/policy/state-storage`
  and place it: nature, owner, loss cost, medium, write isolation, scope and
  lifecycle. Step 2 compares the design against this classification.
- `telec todo artifacts read {slug} architecture` — the index of the design
  under review.
- Every indexed snippet in its pending view, `telec docs get <id> --target {slug}`,
  compared with its current contract — the design under review is the pending
  material, not the live text.
- Relevant code paths cited by the artifact.
- Walk the governing-contracts entry points yourself before you read the
  artifact's Governing contracts section, then compare
  (`preparation-artifact-quality`, Governing contracts).

### 2. Verify grounding

Verify cited code paths, events, services, scaffold choices, and state
ownership against source. Verify solution claims against authoritative prior
art when the design depends on them. Confirm the artifact keeps current
contract, current implementation, credible intended state, inference, and
assumptions distinguishable.

Trace every material architectural choice back to an approved outcome or
constraint. A grounded description of the current code is not enough when the
design fails to carry the target forward.

For every changed behavior, invariant, state transition, validation rule, and
vocabulary decision, verify both coordinates required by
`sdlc/policy/domain-ownership`: one bounded-context owner and
one correct architectural layer inside that owner. Verify every other context
uses an explicit published contract. A cross-cutting design document may own
the relationship only; it cannot be the sole home of a participating domain
rule.

For every piece of durable state the design introduces, relocates or changes,
compare its placement in the indexed snippets with your own classification from
step 1. A piece of state your classification did not anticipate is classified
before you read its reasoning. Verify the design's loss cost, write pattern and
existing store against source.

### 3. Reject undocumented divergence and unsupported invention

Reject divergence from architectural defaults when its trade-off is unstated or
does not serve an approved outcome. Defaults are starting positions, not
authority to narrow intent.

Reject status-quo absorption when the architecture omits or weakens an approved
outcome merely because the current implementation lacks a convenient path. A
departure from current code may be correct; it must name the collision, the
evidence, and why the target earns the change.

For every structural decision, build the alternative the governing paradigm
already gives before you read the author's reasoning. Reject a decision that
never weighs that alternative, rejects it without an argument, or places an
operation callers see outside its governing paradigm without saying what those
callers then wait for (`preparation-artifact-quality`, Structural decisions
carry architecture review).

Against the baseline of the existing path and external primitives named in
step 1, judge every part of the design that departs from them as a cost the
artifact must justify
from an approved outcome; a mechanism built where the existing path or a
primitive already serves is a finding. When a finding you raised is answered by
more mechanism, check before the next pass that the criterion it defends is
carried by the approved intent, not only by the artifact.

Reject bespoke infrastructure or security mechanisms without authoritative
prior-art evidence and an adopt-vs-build judgment. Also reject prior art used as
authority to add product scope: solution evidence advises mechanism and
trade-offs, not intent.

Reject wrong-context placement, duplicated policy in a consumer, host-as-owner
reasoning, or a direct dependency that bypasses the owning context's contract.
These are Critical findings even when the code would sit in the correct
architectural layer or match an adjacent implementation pattern.

Reject durable state the design leaves unclassified, and storage that breaks
`sdlc/policy/state-storage`. Durable state that has no persisted home, or lives
inside a derived store, is Critical. Any other breach is Important: a medium
that does not fit the state's shape, a write-isolation unit shared with a path
people or agents wait on, or an undeclared scope, bound or transfer.

### 4. Write the complete review report

Write `architecture-review-findings` on every pass before stamping, including
every executed lane, the arithmetic verdict, and a clean-pass analysis when no
findings remain:

```bash
telec todo artifacts write {slug} architecture-review-findings <content>
```

The report carries the severity schema and policy citation requirement defined
in the shared review procedure.

### 5. Write verdict

Stamp the review verdict:

```bash
telec todo stamp {slug} --verdict approve --phase architecture_review
# or
telec todo stamp {slug} --verdict needs_work --phase architecture_review
```

## Outputs

- A complete `architecture-review-findings` report for every pass.
- A verdict stamped with `telec todo stamp`, bound to the current architecture
  and report digests.

## Discipline

Review in both directions: the target must survive contact with reality, and
the architecture must survive contact with evidence. Conformance alone and
novelty alone are equally insufficient.

Review the architecture, not the implementation. Do not add scope, do not
write the implementation plan, and do not silently repair architectural
decisions that need the drafter or human to own them.

Apply finding validity, classification, verdict arithmetic and re-review
boundaries from `sdlc/procedure/lifecycle/review`.

## Recovery

- If the PRD is ambiguous about product intent, flag a blocker — the PRD must
  be re-engaged before the architecture can advance. A technical realization
  the architecture chose within an unambiguous outcome is judged against the
  approved outcome, governing contracts and verified substrate, not blocked as
  ambiguity.
- If the architecture diverges from the defaults with an unstated rationale,
  mark `needs_work` rather than guessing the rationale.

## See Also

- ~/.teleclaude/docs/sdlc/procedure/lifecycle/prepare/architecture.md
