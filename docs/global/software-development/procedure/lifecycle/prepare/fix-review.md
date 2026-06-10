---
description: 'Fix phase for prepare. Address review findings inside the active procedure and re-dispatch the reviewer via the state machine.'
visibility: 'public'
---

# Fix Review (Prepare) — Procedure

## Goal

Your focus this turn is to address reviewer findings on the current phase's
artifact, in this session, using the same procedure you used to draft the
artifact. There is no separate "fixer" identity — the BA fixes PRD findings,
the Architect fixes architecture findings, the Planner fixes plan findings. After fixes, advance the
state machine; it routes back to the reviewer.

### Outcome

Read the relevant findings artifact for the active phase:

- Architecture phase: `telec todo artifacts read {slug} architecture-review-findings`
- Plan phase: `telec todo artifacts read {slug} plan-review-findings`

The PRD has no review-findings artifact because the PRD has no automated
reviewer — refinements to the PRD come from the human directly and re-enter
intake.

If the findings artifact is missing: stop and report. If the verdict is
already `APPROVE`: stop and report.

Extract:

- Critical issues (must fix)
- Important issues (should fix)
- Suggestions (optional)

## Preconditions

- The relevant findings artifact exists with a non-`APPROVE` verdict.
- The current phase's procedure is loaded (BA, Architect, or
  Planner — the same procedure that drafted the artifact under review).

## Steps

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

1. Read the findings artifact in full and categorize issues.
2. For each Critical and Important issue: understand the issue and the
   referenced file/line; apply the minimal fix to the artifact under review
   (the PRD is not in this set — PRD findings would be human refinements,
   not reviewer findings).
3. Verify each fix against the artifact's quality bars: grounding, leakage
   discriminator, review-awareness checklist.
4. Update the artifact via
   `telec todo artifacts write {slug} <artifact> <content>`. The artifact
   write IS the deliverable; the reviewer will see it on re-dispatch.
5. Persist any updates to the findings artifact (e.g., a "Fixes Applied"
   section noting issue → fix) via
   `telec todo artifacts write {slug} <findings-artifact> <content>`.
6. **Advance the state machine:**

   ```
   telec todo prepare {slug}
   ```

   The state machine re-dispatches the reviewer against the updated artifact.
   The reviewer runs as a separate session, writes findings and a verdict,
   and idles. The active procedure reads the new findings on the next
   state-machine advance.

## Outputs

- Updated artifact under review, persisted via
  `telec todo artifacts write`, ready for re-review.
- Updated findings artifact with fixes applied (where the schema requires
  tracking them).
- State machine advanced, reviewer re-dispatched.

## Recovery

- **A fix is blocked.** Document the blocker in the findings artifact and
  surface to the user via the state machine; do not grind.
- **A fix introduces a regression.** Revert the fix, document the regression
  in the findings artifact, and move to the next issue.
- **The findings are not actionable** (e.g., reviewer asked for new scope).
  Surface as a blocker — adding scope is the human's call, not the
  reviewer's, and not the fix-review's.
