---
description: Independently review a drafted PRD's horizon, enrichment, scope reasoning, assumptions, and observable outcomes before human approval.
activation_trigger: The prepare state machine routes a feature from PRD drafting to PRD review.
delivered_by:
  - prepare-scope-shaping-and-prd-review
---

# Review PRD — Procedure

## Required reads

@~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
@~/.teleclaude/docs/software-development/policy/definition-of-ready.md
@~/.teleclaude/docs/software-development/concept/reviewer.md

## Goal

Decide whether a drafted `prd` is a trustworthy product contract ready for
human judgment. Review the reasoning that survived into the PRD, then
independently probe for valuable outcomes the draft may have omitted. Do not
review architecture, implementation mechanism, or concrete proof.

## Preconditions

- The todo is a `feature` with a drafted `prd`.
- The PRD has not yet entered human approval.
- The reviewer is dispatched independently from the drafting context.

## Steps

1. Discover the todo's artifacts, then read the `input`, the drafted `prd`, and
   any `log` or deferral material that bears on product intent. Load the relevant
   product and domain snippets. Distinguish observable current behavior,
   credible intended state, implementation detail, prior art, and assumptions.
2. Re-run the shaping questions from the preparation-artifact-quality policy
   from the evidence rather than trusting the draft's answers:
   - What outcome is this work authorized to change?
   - Given that horizon, what would improve the target beyond the input alone,
     and why in this situation?
   - Against the current system and credible intended state, what must change
     for the better target to survive?
   - How is the world observably different when the outcome is achieved?
3. Review the PRD as a product contract:
   - Its authorized horizon is explicit and consistent with the source intent.
   - Domain intelligence enriches the target where the situation earns it; a
     generic best-practice recital does not masquerade as situational need.
   - Each consequential inclusion and exclusion explains why it belongs here,
     resting on an inspectable premise or a named assumption.
   - The present slice is coherent for the project's scale and phase. A future
     concern appears only when it constrains today's choice or has a meaningful
     deferral trigger.
   - Observable outcomes are complete and mechanism-free.
   - Human-owned judgments remain visible instead of being invented or hidden.
4. Compare the independent shaping pass with the PRD. A plausible omission is
   a finding even when the drafter never considered it. Do not demand a ledger
   of discarded ideas or reconstruct the drafting transcript; retained choices
   must justify themselves, and independent re-derivation covers omissions.
5. Preserve reviewer separation. Write findings; do not rewrite the PRD,
   decide product intent, or turn evidence into requirements. Every finding
   cites the preparation contract it violates and states what the intake pass
   must reconsider.
6. When unresolved findings remain, write `prd-review-findings` and stamp
   `needs_work` for `prd_review`. When none remain, stamp `approve` for
   `prd_review`. The state machine returns `needs_work` to intake and routes an
   approved PRD to human approval.

## Outputs

- A digest-bound `prd_review` verdict.
- `prd-review-findings` when the verdict is `needs_work`.
- No edit to the PRD or any downstream artifact.

## Discipline

The failure this review prevents is polished scope whose choosing cannot be
audited: generic additions with no situational reason, valuable coverage
pruned by premature minimalism, and current implementation silently treated as
the limit of product intent. Review the semantic outcome, not whether a ritual
was performed. Re-run the questions to find omissions, but never convert the
reviewer's own recommendations into authority over product intent.

## Recovery

- If source intent is insufficient to determine the authorized horizon, record
  the unresolved human-owned decision and return `needs_work`; do not invent it.
- If the PRD prescribes mechanism, return it to intake for an outcome-shaped
  rewrite rather than solving the mechanism in review.
- If relevant product or domain truth cannot be loaded, report the grounding
  blocker and do not approve from general knowledge alone.
