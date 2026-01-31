---
argument-hint: '[slug]'
description: Orchestrator command - resolve deferrals, create new todos
---

@~/.teleclaude/docs/software-development/role/orchestrator.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/deferrals.md

# Deferral Resolution

You are now the Orchestrator.

## Purpose

Process deferrals, decide outcomes, and create new todos as needed.

## Inputs

- Slug: "$ARGUMENTS"
- `todos/{slug}/deferrals.md`

## Outputs

- Updated `todos/{slug}/deferrals.md`
- New todos in the roadmap (if needed)
- Report format:

  ```
  DEFERRALS PROCESSED: {slug}

  New todos created: {count}
  Marked NOOP: {count}

  Ready to continue.
  ```

## Steps

- Read `todos/{slug}/deferrals.md`.
- For each deferral: decide NEW_TODO or NOOP.
- Create new todos in the roadmap if needed.
- Mark deferrals as processed.
