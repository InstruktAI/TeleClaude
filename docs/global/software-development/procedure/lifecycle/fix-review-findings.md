---
description: 'Address review findings for any review phase: requirements, specs, plan, or build. Single procedure parameterized by the findings artifact name.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/fix-review-findings'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Fix Review Findings — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md

## Goal

Address review findings for a todo and bring the verdict to `APPROVE`. This procedure
applies to every review phase in the lifecycle. The findings artifact name and the
target artifact are provided in the message that dispatched this read — the procedure
itself is artifact-agnostic.

Typical phase/artifact combinations:

- `requirements-review-findings` → target: `requirements`
- `spec-review-findings` → target: test spec files in the worktree
- `plan-review-findings` → target: `implementation-plan`
- `review-findings` → target: source code in the worktree

## Preconditions

- The findings artifact referenced in your dispatch message exists and has a
  non-`APPROVE` verdict.
- The target artifact exists (or the target is a set of files in the worktree).

## Steps

1. **Read the findings.** Load the findings artifact referenced in your dispatch
   message: `telec todo artifacts read {slug} {findings_artifact_name}`. Extract
   Requirement-Violation, Critical, and Important issues. Every finding is
   actionable — there is no "Suggestion" tier to skip.

2. **Address every finding.** For each:
   - Understand the issue and its referenced location.
   - Apply the minimal fix to the target artifact.
   - Verify via commit hooks (lint + unit tests) after each fix.
   - Commit one fix per issue when the target is code. For artifact targets
     (`requirements`, `implementation-plan`), persist the updated artifact via
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

7. **Report FIX COMPLETE** in your session output. Your failure mode is scope expansion —
   address each finding precisely without improving adjacent code.

## Outputs

- Updated target artifact (code, `requirements`, `implementation-plan`, or test specs).
- Updated findings artifact with a "Fixes Applied" section and a verdict reflecting
  the remaining unresolved Requirement-Violation, Critical, and Important findings.

## Recovery

- If a fix is blocked, document the blocker in the findings artifact and request guidance.
- If a fix causes regressions, document in the findings artifact and continue with the next issue.
- If a finding is ambiguous, apply the minimum interpretation — do not invent scope.
