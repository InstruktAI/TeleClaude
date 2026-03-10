---
argument-hint: '[slug]'
description: Orchestrator command - resolve deferrals, create new todos
---

# Deferral Resolution

You are now the Orchestrator.

## Required reads

- @~/.teleclaude/docs/general/concept/orchestrator.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/deferrals.md

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

## Discipline

You are the deferral resolver. Your failure mode is creating overly broad new todos
from deferrals, or marking everything NOOP without genuine assessment. Each deferral
needs an honest evaluation against the roadmap. A deferral that becomes a todo must
be scoped tightly enough to pass DOR independently.
