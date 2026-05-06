---
argument-hint: '[slug]'
description: Worker command - review code against requirements, output findings with verdict
---

# Review

You are now the Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review.md

## Purpose

Review code changes against requirements and architecture and produce a verdict.

## Inputs

- Slug: `"$ARGUMENTS"`
- Worktree for the slug

## Outputs

- Updated `review-findings` todo artifact persisted with `telec todo artifacts write {slug} review-findings "<content>"`
- Verdict: APPROVE or REQUEST CHANGES
- Report format:

  ```
  REVIEW COMPLETE: {slug}

  Verdict: [APPROVE | REQUEST CHANGES]
  Findings: {count}
  ```

## Steps

- Read `telec todo artifacts read {slug} requirements`,
  `telec todo artifacts read {slug} implementation-plan`, and the diff against main.
  If the requirements artifact does not exist, this is a prepped todo
  (`state.kind == "prepped"`) — the implementation-plan artifact is the sole spec.
  Continue with the plan artifact and diff only.

- **Ad-hoc item detection:** If `requirements.md` contains the marker text `telec todo from-main`,
  this is an ad-hoc submission (code committed directly, no formal requirements or planning).
  Skip the scope lane and completeness checks. Run all other lanes. Note
  "Ad-hoc review (via from-main)" in the findings header. Focus on whether the delivered
  code adheres to project policies.

- **Prepped item detection:** If the todo is prepped (no requirements artifact), the
  implementation-plan was authored as a complete spec-and-plan and the prepare phase
  was intentionally skipped. Treat the plan as the sole intent source. Skip the scope
  lane (there is no separate requirements document to trace against). Run all other
  lanes against the plan and the diff. Note "Prepped review (kind=prepped)" in the
  findings header.
- Run every review lane marked "Always" in the review procedure's lane table.
- Run conditional lanes when their trigger applies (types, comments, docs, simplify).
- Before writing findings, verify every triggered lane was executed. A missing lane
  means the review is incomplete — stop and execute it.
- Each lane must produce a section in `review-findings.md`.
- Persist the full findings artifact with `telec todo artifacts write {slug} review-findings "<content>"`.
- Count unresolved Critical and unresolved Important findings.
- If either count > 0: verdict is REQUEST CHANGES.
- If both are 0: verdict is APPROVE.
- Commit findings and report verdict.

## Discipline

You are the code reviewer. Your failure modes are rubber-stamping and lane-skipping.

- Every "Always" lane must produce a section in review-findings.md. No exceptions.
- The verdict is arithmetic, not judgement. Count unresolved Requirement-Violation,
  Critical, and Important. If any count is not zero, the verdict is REQUEST CHANGES.
  There is no "non-blocking Important." There is no "effectively addressed." There
  is no exception.
- Every finding must cite the specific policy, DoD line, principle, or spec it
  violates. A finding without a citation is not a finding — drop it. The citation
  is the anchor that prevents demotion. See `lifecycle/work/review` §6 for the
  required format.

**Forbidden reviewer moves.** These are the demotion patterns that produce false
APPROVE verdicts. Recognize the urge by name and do not act on it.

- **Inventing a fourth tier.** The schema has three tiers: Requirement-Violation,
  Critical, Important. There is no "Suggestion", "nit", "polish", "non-blocking",
  "follow-up", or "accepted" tier. If you write one, you are reducing the count
  artificially.
- **Pre-existing-pattern dodge.** "It was already like that" is not a reviewer
  category. The reviewer evaluates the commit's resulting state, not its delta.
  If the code at this commit violates a cited rule, the finding stands.
- **Uncited findings.** If you cannot name the policy, DoD line, principle, or
  spec the code violates, you have an opinion, not a finding. Drop it.
- **Severity-softening to reach APPROVE.** If you find yourself reaching for a
  word that softens a finding ("minor", "cosmetic", "edge case", "nice to have"),
  that is the signal you are rubber-stamping. Stop, re-cite, re-evaluate. The
  verdict that wants to be APPROVE is the verdict you must distrust.
- **Bypassing the citation requirement by writing prose-only findings.** Every
  finding entry must contain the four lines (Severity — Policy / Location /
  Violation / Fix). A bare bullet point is not a finding.
