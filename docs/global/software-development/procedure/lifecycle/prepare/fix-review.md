---
description: 'Fix phase for prepare. Address review findings iteratively with the reviewer via direct link, close before stamping.'
id: 'software-development/procedure/lifecycle/prepare/fix-review'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
---

# Fix Review (Prepare) — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md

## Goal

Read the relevant findings artifact:

- PRD phase: `telec todo artifacts read {slug} requirements-review-findings`
- Test spec phase: `telec todo artifacts read {slug} spec-review-findings`
- Plan phase: `telec todo artifacts read {slug} plan-review-findings`

If missing: stop and report. If verdict already APPROVE: stop and report.

Extract:

- Critical issues (must fix)
- Important issues (should fix)
- Suggestions (optional)

For each Critical and Important issue:

1. Understand the issue and referenced file/line.
2. Apply the minimal fix.
3. Verify via commit hooks (lint + unit tests).
4. Commit one fix per issue, following the commits policy.

Add a "Fixes Applied" section with issue, fix, and commit hash.
Keep the verdict aligned with unresolved findings:

- If any Critical or Important findings remain unresolved, keep `REQUEST CHANGES`.
- If all Critical and Important findings are resolved, change the verdict to `APPROVE`.
- Persist every findings update with:
  `telec todo artifacts write {slug} {findings-artifact} "<content>"`

Report summary and readiness for re-review.

- If unclear: add a clarification comment in the findings artifact and continue.
- If fix causes regressions: document and continue to next issue.
- If stuck: document what was tried and continue.

## Preconditions

- The relevant findings artifact exists with a non-APPROVE verdict.

## Steps

1. Read findings and categorize issues.
2. Apply minimal fixes for Critical and Important issues.
3. Verify via lint/unit tests after each fix.
4. Update the findings artifact with fixes applied via `telec todo artifacts write`.
5. If a `--direct` peer link exists with the reviewer session: respond to reviewer
   feedback inline, address findings iteratively, and update the verdict by arithmetic:
   `APPROVE` only when unresolved Critical and Important counts both reach zero;
   otherwise keep `REQUEST CHANGES`. Silence is a valid response when the reviewer's
   message requires only action.
6. **Before reporting FIX COMPLETE, close the direct link with:**
   `telec sessions send <reviewer_session_id> --close-link`
   This is mandatory in prepare because review phases run sequentially against
   the same conversation lane — a stale link from one phase corrupts the next phase's dispatch.
7. Commit all files in the worktree. Everything in the worktree belongs to the task.

## Outputs

- Updated findings todo artifact, persisted via `telec todo artifacts write`, with fixes applied and ready for re-review.
- Direct link closed before reporting FIX COMPLETE.

## Recovery

- If a fix is blocked, document the blocker and request guidance.
