---
argument-hint: '[slug]'
description: Worker command - fix issues identified in code review findings
---

# Fix Review Issues

You are now the Fixer.

## Required reads

- @~/.teleclaude/docs/software-development/concept/fixer.md
- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/fix-review.md

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
- Treat orchestrator-managed planning/state drift as non-blocking:
  - `todos/roadmap.yaml`
  - `todos/{slug}/state.yaml`
- Do not commit those orchestrator-managed drift files unless the fix explicitly requires planning/state edits.
- Verify tests and lint pass before reporting completion.
