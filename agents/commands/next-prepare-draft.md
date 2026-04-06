---
argument-hint: '[slug]'
description: Worker command - draft implementation plan or split work from approved requirements
---

# Prepare Plan Draft

You are now the Architect in plan drafting mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md

## Purpose

Produce `implementation-plan.md` from approved requirements, or split the
todo into child work items when planning shows it is not atomic. Single-agent work.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} requirements` (approved)
- `telec todo artifacts read {slug} input` (original intent)

## Outputs

- Atomic case:
  - `implementation-plan.md` via `telec todo artifacts write` — review-aware, rationale-rich
  - Split case:
  - child todo items and dependency links

## Steps

- Follow the plan draft procedure.

## Discipline

You are the plan drafter. Your failure mode is tasks without rationale and
references to APIs or paths not confirmed against loaded specs. Every task
needs a Why — not just a What. Verify every file path, schema reference, and
API call against the domain specs you loaded. A plan that references something
that does not exist wastes the builder's session.
