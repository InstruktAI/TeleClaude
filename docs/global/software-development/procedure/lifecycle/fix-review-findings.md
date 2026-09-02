---
description: 'Address review findings for any review phase: prepared artifacts, plan, or build. Single procedure parameterized by the findings artifact name.'
visibility: 'public'
---

# Fix Review Findings — Procedure

## Goal

Address review findings for a todo and bring the verdict to `APPROVE`. This procedure
applies to every review phase in the lifecycle. The findings artifact name and the
target artifact are provided in the message that dispatched this read — the procedure
itself is artifact-agnostic.

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
`software-development/policy/definition-of-done-lanes` (Bug-fix review lane).
When all three of its conditions hold, the finding resolves via a `log` entry,
not a kickback; the reviewer's verdict should already reflect this before this
procedure is ever dispatched.

## Preconditions

- The findings artifact referenced in your dispatch message exists and has a
  non-`APPROVE` verdict.
- The target artifact exists (or the target is a set of files in the worktree).

## Steps

1. **Read the findings.** Load the findings artifact referenced in your dispatch
   message: `telec todo artifacts read {slug} {findings_artifact_name}`. Extract
   Requirement-Violation, Critical, and Important issues. Every finding is
   actionable — there is no "Suggestion" tier to skip. An investigation lead is
   not a finding: it never enters remediation, requires no response from you,
   and cannot enlarge the current work. Address findings; leave leads where the
   reviewer put them.

2. **Address every finding.** For each:
   - Understand the issue and its referenced location.
   - Apply the minimal fix that satisfies the finding's closure condition. The
     closure condition is the contract; the reviewer's wording is not a design.
     You may not fold reviewer conjecture, or your own, into the artifact:
     every mechanism you add is defensible from authorized intent or from a
     principle applied to verified substrate, or it is invention.
   - Verify after each fix: lint runs at the commit gate; run scenario-bound functional tests separately via `telec code test`.
   - Commit one fix per issue when the target is code. For artifact targets
     (`architecture`, `implementation-plan`, or legacy `requirements`),
     persist the updated artifact via
     `telec todo artifacts write {slug} {target_artifact_name} "<content>"`.

3. **Update the findings artifact** with a "Fixes Applied" section recording each
   issue, the fix, and the commit hash (for code fixes) or the artifact version
   timestamp (for artifact fixes). Persist via
   `telec todo artifacts write {slug} {findings_artifact_name} "<content>"`.

4. **Update the verdict by arithmetic.** If any Requirement-Violation, Critical,
   or Important findings remain unresolved, keep the current non-`APPROVE` verdict.
   If every finding is resolved, change the verdict to `APPROVE`.

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
- Updated findings artifact with a "Fixes Applied" section and a verdict reflecting
  the remaining unresolved Requirement-Violation, Critical, and Important findings.

## Recovery

- If a fix is blocked, document the blocker in the findings artifact and request guidance.
- If a fix causes regressions, document in the findings artifact and continue with the next issue.
- If a finding is ambiguous, apply the minimum interpretation — do not invent scope.
