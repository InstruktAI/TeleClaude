---
description: 'Fix phase. Address review findings with minimal changes and re-verify.'
id: 'software-development/procedure/lifecycle/work/fix-review'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
---

# Fix Review — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md

## Goal

Read `todos/{slug}/review-findings.md`.

- If missing: stop and report.
- If verdict already APPROVE: stop and report.

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
Do not change the verdict.

Report summary and readiness for re-review.

- If unclear: add a clarification comment in review-findings.md and continue.
- If fix causes regressions: document and continue to next issue.
- If stuck: document what was tried and continue.

## Preconditions

- `todos/{slug}/review-findings.md` exists with a non-APPROVE verdict.

## Steps

1. Read review findings and categorize issues.
2. Apply minimal fixes for Critical and Important issues.
3. Verify via lint/unit tests after each fix.
4. Record fixes with commit hashes in review-findings.
5. If a `--direct` peer link exists with a reviewer session: respond to reviewer
   feedback inline, address findings iteratively, and update the verdict to APPROVE
   when all findings are resolved. Silence is a valid response when the reviewer's
   message requires only action.

## Outputs

- Updated review findings with fixes applied and ready for re-review.

## Recovery

- If a fix is blocked, document the blocker and request guidance.
