---
argument-hint: '[slug]'
description: Worker command - review implementation plan against policies, DoD gates, and review lanes
---

# Review Plan

You are now the Architect in plan review mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/review-plan.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md
- @docs/_snippets/slug-resolution.md

## Purpose

Validate `implementation-plan.md` against policies, Definition of Done gates, and review lane expectations. Stamp a binary verdict via `telec todo stamp {slug} --verdict approve|needs_work --phase plan_review`.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} implementation-plan` (the artifact under review)
- `telec todo artifacts read {slug} prd` (the product contract it must satisfy)
- `telec todo artifacts read {slug} architecture` when present (thin
  doc-edit index; consult the domain/design snippets it points to)

## Outputs

- Verdict stamped via `telec todo stamp {slug} --verdict approve|needs_work --phase plan_review`
- `plan-review-findings.md` via `telec todo artifacts write` if findings exist
- All review artifacts stored via `telec todo artifacts write`

## Steps

Follow the review-plan procedure.

## Discipline

Follow the review-plan procedure's discipline.
