---
id: 'software-development/procedure/lifecycle/bugs-fix'
type: 'procedure'
scope: 'domain'
description: 'Bug fix phase. Investigate, document, fix, and verify a reported bug in a worktree.'
---

# Bug Fix — Procedure

## Goal

Investigate a bug using systematic debugging, apply the minimal fix, and document
findings in `bug.md` for reviewer verification.

## Preconditions

- `todos/{slug}/bug.md` exists with symptom and discovery context.
- Worktree is available for the slug.

## Steps

1. Read `todos/{slug}/bug.md` to understand the symptom and discovery context.
2. Invoke systematic debugging before making changes — reproduce first,
   then bisect and isolate the root cause.
3. Document the investigation in the `## Investigation` section of `bug.md`.
4. Identify and document the root cause in the `## Root Cause` section.
5. Apply the minimal fix required.
6. Document what changed in the `## Fix Applied` section.
7. Commit the fix and `bug.md` updates together.
8. Run tests: `make test`.
9. Run lint: `make lint`.
10. Verify no unexpected dirty files remain.

## Outputs

- Updated `bug.md` with Investigation, Root Cause, and Fix Applied sections.
- Commits for the fix.

## Report format

```
BUG FIX COMPLETE: {slug}

Symptom: {brief symptom}
Root Cause: {brief root cause}
Fix: {brief fix description}
Tests: PASSING
Lint: PASSING

Ready for review.
```

## Recovery

- If the bug cannot be reproduced, document the investigation and report the blocker.
- If the fix introduces a regression, fix the regression immediately.
