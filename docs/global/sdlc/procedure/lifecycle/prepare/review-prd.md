---
description: Independently review a drafted PRD's horizon, enrichment, scope reasoning,
  assumptions, and observable outcomes before human approval.
activation_trigger: The prepare state machine routes a feature from PRD drafting to
  PRD review.
role: prd-reviewer
parameters:
  - name: slug
    required: true
dispatch:
  agent: [codex, claude, gemini, deepseek]
  thinking_mode: slow
---

# Review PRD — Procedure

## Required reads

@~/.teleclaude/docs/sdlc/procedure/lifecycle/review.md
@~/.teleclaude/docs/sdlc/policy/preparation-artifact-quality.md
@~/.teleclaude/docs/sdlc/policy/definition-of-ready.md

## Goal

Decide whether a drafted `prd` is a trustworthy product contract ready for
human judgment, and whether an earlier human approval carries to it. Review the authority and reasoning that survived into the PRD,
then independently probe for supported outcomes the draft may have omitted. Do
not review architecture, implementation mechanism, or concrete proof.

## Preconditions

- The todo is a `feature` with a drafted `prd`.
- The PRD has not yet entered human approval.
- The reviewer is dispatched independently from the drafting context.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

1. Discover the todo's artifacts, then read the `input`, the drafted `prd`, and
   any `log` or deferral material that bears on product intent. Load the relevant
   product and domain snippets. Take the `input` as the authorized basis.
   Distinguish observable current behavior, credible intended state,
   implementation detail, prior art, and assumptions.
2. Re-run the shaping questions from the preparation-artifact-quality policy
   from the evidence rather than trusting the draft's answers:
   - What outcome is this work authorized to change?
   - What product outcome and constraints does that authority actually support?
   - Against the current system and credible intended state, what must change
     for the better target to survive?
   - How is the world observably different when the outcome is achieved?
3. Review the PRD as a product contract:
   - Its authorized horizon is explicit and consistent with the source intent.
   - Every consequential product or business detail stays within what the
     input carries; a detail beyond it is scope the PRD added on its own
     authority. If another reasonable realization could satisfy the input while
     omitting or varying that detail, it is unspecified and cannot enter the
     PRD as decided scope. This test decides: a stated reason for a detail,
     including that it follows from the input's outcome, never stands in for
     the input carrying it.
   - Each consequential inclusion the input carries, and each exclusion,
     explains why it belongs here, resting on an inspectable premise or a named
     assumption.
   - The present slice is coherent for the project's scale and phase. A future
     concern appears only when it constrains today's choice or has a meaningful
     deferral trigger.
   - Observable outcomes are complete and mechanism-free.
   - Human-owned judgments remain visible instead of being invented or hidden.
4. Compare the independent shaping pass with the PRD. A plausible omission is
   a finding only when existing authority makes it part of the outcome; a
   desirable addition requiring fresh product or business judgment is an open
   human decision, not a missing requirement. An adjacent context's deficiency
   becomes a dependency,
   a separately scoped proposal, or a human-owned boundary decision — never a
   requirement that the current item absorb that context's behavior. Do not
   demand a ledger of discarded ideas or reconstruct the drafting transcript;
   retained choices must justify themselves, and independent re-derivation
   covers omissions.
5. Preserve reviewer separation. Write findings; do not rewrite the PRD,
   decide product intent, or turn evidence into requirements. Every finding
   cites the preparation contract it violates and states what the intake pass
   must reconsider.
6. When the human approved an earlier digest of this PRD
   (`approved_digest` in `telec todo show {slug}`), judge whether that
   approval carries to this revision under the carry rule owned by
   `sdlc/procedure/lifecycle/prepare/overview`. Compare the two versions with
   `telec todo artifacts diff {slug} prd <approved-digest> <current-digest>`.
   In an `## Approval carry` section, state for each change the ground it
   carries on or why it needs the human, and conclude `carries` or
   `returns to the human`; an uncertain change returns. This judgment is not a
   finding and does not enter the verdict.
7. Write the complete `prd-review-findings` report for this pass, including all
   review sections and the verdict even when no findings remain. Classify and
   cite every finding under the severity schema and citation requirement the
   shared review procedure defines, and derive the verdict arithmetically from
   the unresolved findings in those tiers. Then stamp
   `needs_work` or `approve` for `prd_review`. The stamp binds the current PRD
   digest and the current report digest. The state machine returns `needs_work`
   to intake and routes a current approved PRD to human approval.

## Outputs

- A complete `prd-review-findings` report for every pass, with an
  `## Approval carry` conclusion whenever an earlier human approval exists.
- A `prd_review` verdict bound to the current PRD and report digests.
- No edit to the PRD or any downstream artifact.

## Discipline

Judge the PRD as an intent contract, not as architecture or an implementation
plan. Re-run the shaping questions to probe omissions, while auditing retained
scope against its stated premises. Write findings and the verdict only; never
repair the PRD from inside its independent review.

The failure this review prevents is polished scope whose authority cannot be
audited. A human concern about misuse does not authorize an invented numeric
cap, and evidence for one concern does not ratify an entire agent-authored
contract. Review the semantic outcome, not whether a ritual was performed.
Re-run the questions to find supported omissions, but never convert the
reviewer's own recommendations into authority over product intent.

Apply the finding-validity, classification and verdict rules in
`sdlc/procedure/lifecycle/review`.

## Recovery

- If source intent is insufficient to determine the authorized horizon, record
  the unresolved human-owned decision; do not invent it. A PRD that omits or
  contradicts an outcome the input authorizes is a finding under the shared
  validity rules; an optional proposal needing fresh product judgment is an open
  human decision, not a finding. The verdict follows the shared arithmetic.
- If a desirable omission belongs to a different bounded context or requires a
  boundary redraw, record that ownership fact without making it a requirement
  of the PRD under review.
- If the PRD prescribes mechanism, return it to intake for an outcome-shaped
  rewrite rather than solving the mechanism in review.
- If relevant product or domain truth cannot be loaded, report the grounding
  blocker and do not approve from general knowledge alone.
