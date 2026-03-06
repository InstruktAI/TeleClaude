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

- Follow the fix-review procedure.
- Do not self-terminate — the orchestrator always ends child sessions.
