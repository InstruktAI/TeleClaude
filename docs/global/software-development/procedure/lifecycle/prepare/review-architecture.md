---
description: 'Architecture review phase. Validate the architecture artifact against the approved PRD, project architecture, codebase reality, and platform defaults.'
visibility: 'public'
---

# Review Architecture — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review-build.md

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

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

### 1. Read context

- Apply the artifact-discovery rule from `preparation-artifact-quality`
  (`telec todo artifacts list {slug}`) — read `log` when present, and any
  other present artifact relevant to this review.
- `telec todo artifacts read {slug} prd` — the approved product contract.
- `telec todo artifacts read {slug} architecture` — the artifact under review.
- Relevant code paths and project architecture docs cited by the artifact.
- Apply the domain-context loading rule from the preparation artifact quality
  policy before validating.

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
`software-development/policy/domain-ownership`: one bounded-context owner and
one correct architectural layer inside that owner. Verify every other context
uses an explicit published contract. A cross-cutting design document may own
the relationship only; it cannot be the sole home of a participating domain
rule.

### 3. Reject undocumented divergence and unsupported invention

Reject divergence from architectural defaults when its trade-off is unstated or
does not serve an approved outcome. Defaults are starting positions, not
authority to narrow intent.

Reject status-quo absorption when the architecture omits or weakens an approved
outcome merely because the current implementation lacks a convenient path. A
departure from current code may be correct; it must name the collision, the
evidence, and why the target earns the change.

Reject bespoke infrastructure or security mechanisms without authoritative
prior-art evidence and an adopt-vs-build judgment. Also reject prior art used as
authority to add product scope: solution evidence advises mechanism and
trade-offs, not intent.

Reject wrong-context placement, duplicated policy in a consumer, host-as-owner
reasoning, or a direct dependency that bypasses the owning context's contract.
These are Critical findings even when the code would sit in the correct
architectural layer or match an adjacent implementation pattern.

### 4. Write findings only when unresolved issues remain

When findings exist, write them via:

```bash
telec todo artifacts write {slug} architecture-review-findings <content>
```

Findings carry the severity schema and policy citation requirement defined
in `lifecycle/work/review` §6.

### 5. Write verdict

Stamp the review verdict:

```bash
telec todo stamp {slug} --verdict approve --phase architecture_review
# or
telec todo stamp {slug} --verdict needs_work --phase architecture_review
```

## Outputs

- Verdict stamped with `telec todo stamp`.
- `telec todo artifacts read {slug} architecture-review-findings` when findings
  exist.

## Discipline

Review in both directions: the target must survive contact with reality, and
the architecture must survive contact with evidence. Conformance alone and
novelty alone are equally insufficient.

Review the architecture, not the implementation. Do not add scope, do not
write the implementation plan, and do not silently repair architectural
decisions that need the drafter or human to own them.

- Every finding must cite the specific policy, DoD line, principle, or
  spec it violates. A finding without a citation is not a finding — drop it.
- The schema mirrors the plan-review and specs-review forbidden-moves block:
  no fourth tier (no "Suggestion", "nit", "polish", "non-blocking",
  "follow-up"); no pre-existing-pattern dodge; no uncited findings; no
  severity-softening to reach approve.

## Recovery

- If the architecture is materially correct but PRD is ambiguous, flag a
  blocker — the PRD must be re-engaged before the architecture can advance.
- If the architecture diverges from the defaults with an unstated rationale,
  mark `needs_work` rather than guessing the rationale.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/architecture.md
