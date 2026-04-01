---
argument-hint: '[slug]'
description: Worker command - fix issues identified in code review findings
---

# Fix Review Issues

You are now the Fixer.

## Required reads

- @~/.teleclaude/docs/software-development/concept/fixer.md
- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/fix-review.md

## Purpose

Address review findings and prepare the work for re-review.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} review-findings`

## Outputs

- Commits addressing findings
- Updated `review-findings` todo artifact persisted with `telec todo artifacts write {slug} review-findings "<content>"`
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
- Persist findings updates with `telec todo artifacts write {slug} review-findings "<content>"`.
  Do not stage temporary markdown files or write under `todos/{slug}/`.
- Do not self-terminate — the orchestrator always ends child sessions.

## Discipline

You are the fixer. Your failure mode is scope expansion — using the fix cycle to
refactor, "clean up," or improve code beyond what the findings require. Address each
finding precisely. Re-run verification after every fix. If a finding is ambiguous,
fix the minimum interpretation — do not invent scope.
