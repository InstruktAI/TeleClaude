---
description: 'Address review findings for any review phase: prepared artifacts, plan, or build. Single procedure parameterized by the findings artifact name.'
visibility: 'public'
---

# Fix Review Findings — Procedure

## Goal

Adjudicate review findings for a todo and converge the target without enlarging
its frozen scope. This procedure applies to every review phase in the lifecycle.
The findings artifact name and the target artifact are provided in the message
that dispatched this read — the procedure itself is artifact-agnostic.

Typical phase/artifact combinations:

- `architecture-review-findings` → target: `architecture`
- `plan-review-findings` → target: `implementation-plan`
- `review-findings` → target: source code in the worktree

Legacy todos may still reference `requirements-review-findings` → `requirements`.
New prepare work uses human `prd_approved` rather than a requirements review phase.

The artifact targets (`architecture`, `implementation-plan`) are writable only
during the prepare review-fix loops, which the prepare orchestrator runs. In the
work build-review loop the target is `review-findings` → code; a finding that
implicates a prepare artifact is not fixed here — it bounces the todo to prepare.
The workflow service refuses prepare-artifact writes from work-phase sessions, so
a work-phase fixer cannot target one regardless of the dispatch message.

A finding against a prepare artifact's own narrative does not automatically
bounce, though — check it first against the record-drift exception in
`sdlc/policy/definition-of-done-lanes` (Bug-fix review lane).
When all three of its conditions hold, the finding resolves via a `log` entry,
not a kickback; the reviewer's verdict should already reflect this before this
procedure is ever dispatched.

## Preconditions

- The findings artifact referenced in your dispatch message exists and has a
  non-`APPROVE` verdict.
- The target artifact exists (or the target is a set of files in the worktree).

## Steps

1. **Read and contest the findings.** Load the findings artifact referenced in
   your dispatch message:
   `telec todo artifacts read {slug} {findings_artifact_name}`. Extract
   Requirement-Violation, Critical, and Important issues. A finding is an
   adversarial claim, never an instruction: independently re-establish its
   citation, applicability, causal contradiction, and fit with the frozen scope.
   Every finding requires a disposition; that requirement establishes neither
   truth nor design authority. An investigation lead is not a finding: it never
   enters remediation, requires no response from you, and cannot enlarge the
   current work. Address findings; leave leads where the reviewer put them.

   <!-- planned:retire-assist-review-loop-watcher -->
   Before remediating a further finding in work you already remediated, compare
   it with the earlier finding, its disposition, and the change that answered it;
   a repeated failure on the same invariant re-derives the affected unit rather
   than patching it again (`sdlc/procedure/lifecycle/review`). A grounded defect
   in continuing the loop is raised to the phase orchestrator, which owns
   continuation under the same contract.
   <!-- /planned:retire-assist-review-loop-watcher -->

2. **Dispose of every finding, then remediate the fixes.** Each finding
   receives exactly one disposition, written before any remediation: **fix**,
   **reject**, or **kick back**. Record each disposition in the findings artifact
   before editing. For a fix, cite the governing clause and the source
   observation that independently establish its applicability and the
   contradiction; the reviewer's assertion is not that evidence (finding
   validity: `sdlc/procedure/lifecycle/review`). A finding is fixed only when it cites a clause
   that applies, establishes the contradiction, and its closure stays within the
   frozen scope. One that does not establish its clause, or whose closure
   enlarges the horizon — new functionality, instrumentation, subsystems, or
   scope beyond the frozen denominator — is rejected with the evidence and
   stands rejected until the reviewer overturns it on changed substrate or
   material new evidence
   (`sdlc/procedure/lifecycle/review` §6); a finding that
   enlarges the horizon is invalid under
   `sdlc/policy/definition-of-done-lanes`. A valid omission
   finding — a missing reflection, verification, or gate the policies require
   on the authorized work — adds material within scope and is fixed, not
   rejected. Kick back only when a valid finding establishes that resolution
   belongs to an upstream authority or different owner. A finding cannot create
   that boundary by proposing it. For each finding
   you fix:
   - Understand the issue and its referenced location.
   - Apply the minimal fix that satisfies the independently validated invariant.
     The reviewer's closure wording is neither design nor authority for a
     mechanism. You may not fold reviewer conjecture, or your own, into the artifact:
     every mechanism you add is defensible from authorized intent or from a
     principle applied to verified substrate, or it is invention.
   - Verify after each fix: lint runs at the commit gate; run tests only as the project's testing contract binds them (`sdlc/policy/testing`).
   - Commit one fix per issue when the target is code. For artifact targets
     (`architecture`, `implementation-plan`, or legacy `requirements`),
     persist the updated artifact via
     `telec todo artifacts write {slug} {target_artifact_name} "<content>"`.

3. **Update each disposition with its outcome** in the findings artifact's
   "Dispositions" section: for a fix, the change and its commit hash (code) or
   artifact version (artifact); for a rejection, the grounded reason and the
   source it rests on; for a kickback, the destination and the unresolved
   issue. Persist via
   `telec todo artifacts write {slug} {findings_artifact_name} "<content>"`.

4. **Leave the verdict to the reviewer.** Do not change the verdict in the
   findings artifact. Your "Dispositions" section is remediation evidence; the
   continuing reviewer re-evaluates the target against it, updates the report,
   and stamps the arithmetic verdict. A fixer-written `APPROVE` bypasses
   reviewer authority and the bounded convergence contract.

5. **Commit worktree state.** Everything in the worktree belongs to the task —
   commit all files in the worktree.

6. **Stamp build completion** after code-review fixes: `telec todo stamp {slug} --build-complete`.
   For non-code prepare artifact fixes, use the verdict or artifact stamp named in the dispatch message instead.

7. **Close the review link, then report FIX COMPLETE.** If a `--direct` link with a
   reviewer session is open (the work build-review fix loop), close it before reporting:
   `telec sessions send <reviewer_session_id> --close-link`. Then report FIX COMPLETE in
   your session output. Your failure mode is scope expansion — address each finding
   precisely without improving adjacent code.

## Outputs

- Updated target artifact (code, `architecture`, `implementation-plan`,
  or legacy `requirements`).
- Updated findings artifact with a "Dispositions" section carrying the
  producer's evidence; its verdict remains reviewer-authored.

## Recovery

- If a fix is blocked, document the blocker in the findings artifact and request guidance.
- If a fix causes regressions, document in the findings artifact and continue with the next issue.
- If a finding or closure condition is ambiguous, do not interpret or remediate it; return it to review for clarification or reclassification. A lead remains outside remediation.
