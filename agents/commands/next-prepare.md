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

Run the next-prepare step to bring todos to Definition-of-Ready.
Same process, two scopes:

- with slug: prepare one todo
- without slug: process active todos needing preparation

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- `todos/{slug}/requirements.md` (if slug provided)
- `todos/{slug}/implementation-plan.md` (if slug provided)
- `todos/{slug}/dor-report.md` and `state.json.dor` updates when assessed
- Report format:

  ```
  PREPARED: {slug}

  Requirements: todos/{slug}/requirements.md [COMPLETE]
  Implementation Plan: todos/{slug}/implementation-plan.md [COMPLETE]

  Ready for build phase.
  ```

## Steps

- If slug is given: prepare that slug.
- If no slug is given: run the same preparation logic over active todos needing work.
