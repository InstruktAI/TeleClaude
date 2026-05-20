---
argument-hint: '[slug]'
description: Worker command - draft implementation plan or split work from approved v2 prepare artifacts
---

# Prepare Plan

You are now the Architect in plan drafting mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md
- @docs/_snippets/slug-resolution.md

## Purpose

Produce `implementation-plan` from the approved PRD and the optional approved
architecture (the thin index/log artifact plus the doc snippets it points
at); or split the todo when planning proves it is not atomic.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} prd`
- `telec todo artifacts read {slug} architecture` when present and not skipped —
  the thin index/log; read the domain-spec / design-doc snippets it points at
  for the actual design content
- `telec todo artifacts read {slug} input` only as a legacy fallback when PRD is absent
- Existing `plan-review-findings` when present

## Outputs

- Atomic case: `implementation-plan` via `telec todo artifacts write {slug} implementation-plan <content>`
- Split case: child todo items and dependency links

## Steps

Follow the plan-draft procedure.

## Discipline

Follow the plan-draft procedure's discipline.
