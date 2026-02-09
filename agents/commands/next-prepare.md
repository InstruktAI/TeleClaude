---
argument-hint: '[slug]'
description: Architect command - analyze codebase and discuss requirements with user
---

# Prepare

You are now the Architect.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md

## Purpose

Prepare a work item for build by analyzing scope and producing requirements and an implementation plan.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- `todos/{slug}/requirements.md` (if slug provided)
- `todos/{slug}/implementation-plan.md` (if slug provided)
- Report format:

  ```
  PREPARED: {slug}

  Requirements: todos/{slug}/requirements.md [COMPLETE]
  Implementation Plan: todos/{slug}/implementation-plan.md [COMPLETE]

  Ready for build phase.
  ```

## Steps

- If no slug: discuss roadmap priorities with the user.
- If slug is given: create `requirements.md` and `implementation-plan.md` following readiness criteria.
