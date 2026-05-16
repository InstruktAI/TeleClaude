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
- @~/.teleclaude/docs/_snippets/slug-resolution.md

## Purpose

Produce `implementation-plan` from the approved PRD, optional approved
architecture, and optional approved prose test-specs; or split the todo when
planning proves it is not atomic.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} prd`
- `telec todo artifacts read {slug} architecture` when present and not skipped
- `telec todo artifacts read {slug} test-specs` when present and not skipped
- `telec todo artifacts read {slug} input` only as a legacy fallback when PRD is absent
- Existing `plan-review-findings` when present

## Outputs

- Atomic case: `implementation-plan` via `telec todo artifacts write {slug} implementation-plan <content>`
- Split case: child todo items and dependency links

## Steps

- Follow the plan-draft procedure.
- If architecture or test-specs were skipped, read the skip reason from todo state and account for it in plan rationale.
- Keep tasks grounded in PRD criteria, architecture constraints, test-spec cases, and verified code paths.
- Do not stamp `plan_approved`; that stamp is reserved for human approval after review.
- Go idle after writing the plan or performing the split.

## Discipline

Every task needs a why, explicit files or surfaces where knowable, and a
verification step. A builder should be able to execute the plan without guessing.
