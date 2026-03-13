---
id: 'software-development/procedure/lifecycle/work/bug-fix'
type: 'procedure'
domain: 'software-development'
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
2. Follow the systematic debugging procedure before making changes — reproduce first,
   then bisect and isolate the root cause.
3. Encode the reproduction as a failing test. Write a test that triggers the bug.
   Run the test suite — the new test must FAIL (RED). If you cannot write a test
   for it, document why in `bug.md`.
4. Document the investigation in the `## Investigation` section of `bug.md`.
5. Identify and document the root cause in the `## Root Cause` section.
6. Apply the minimal fix required.
7. Run the test suite — the reproduction test must now PASS (GREEN). The fix is
   not complete until the test passes.
8. Document what changed in the `## Fix Applied` section.
9. Commit the fix and `bug.md` updates together.
10. Run tests: `make test`.
11. Run lint: `make lint`.
12. Verify no unexpected dirty files remain.

## Pre-completion checklist

- Reproduction test exists and passes.
- All tests pass: `make test`.
- Lint passes: `make lint`.

## Outputs

- Updated `bug.md` with Investigation, Root Cause, and Fix Applied sections.
- Reproduction test for the bug.
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
