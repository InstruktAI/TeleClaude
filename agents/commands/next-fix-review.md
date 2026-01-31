---
argument-hint: '[slug]'
description: Worker command - fix issues identified in code review findings
---

@~/.teleclaude/docs/software-development/role/fixer.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/fix-review.md

# Fix Review Issues

You are now the Fixer.

## Purpose

Address review findings and prepare the work for re-review.

## Inputs

- Slug: "$ARGUMENTS"
- `todos/{slug}/review-findings.md`

## Outputs

- Commits addressing findings
- Report format:

  ```
  FIX COMPLETE: {slug}

  Findings addressed: {count}
  Commits made: {count}
  Tests: PASSING
  Lint: PASSING

  Ready for re-review.
  ```

## Steps

- Address findings in `todos/{slug}/review-findings.md`, prioritizing by severity.
- Commit per fix.
- Verify tests and lint pass before reporting completion.
