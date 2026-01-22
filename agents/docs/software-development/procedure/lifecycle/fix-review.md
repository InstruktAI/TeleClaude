---
description: Fix phase. Address review findings with minimal changes and re-verify.
id: software-development/procedure/lifecycle/fix-review
scope: domain
type: procedure
---

# Lifecycle: Fix Review Findings

## 1) Load Review Findings

Read `todos/{slug}/review-findings.md`.

- If missing: stop and report.
- If verdict already APPROVE: stop and report.

## 2) Parse Issues

Extract:

- Critical issues (must fix)
- Important issues (should fix)
- Suggestions (optional)

## 3) Fix Each Issue

For each Critical and Important issue:

1. Understand the issue and referenced file/line.
2. Apply the minimal fix.
3. Verify via commit hooks (lint + unit tests).
4. Commit one fix per issue.

## 4) Update Review Findings

Add a "Fixes Applied" section with issue, fix, and commit hash.
Do not change the verdict.

## 5) Request Re-review

Report summary and readiness for re-review.

## Error Handling

- If unclear: add a clarification comment in review-findings.md and continue.
- If fix causes regressions: document and continue to next issue.
- If stuck: document what was tried and continue.
