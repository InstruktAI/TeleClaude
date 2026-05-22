---
argument-hint: '[slug]'
description: Orchestrator command - resolve deferrals, create new todos
---

# Deferral Resolution

You are now the Orchestrator.

## Required reads

- @~/.teleclaude/docs/general/concept/orchestrator.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/deferrals.md
- @docs/_snippets/slug-resolution.md

## Purpose

Process deferrals, decide outcomes, and create new todos as needed.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} deferrals`

## Outputs

- Updated `telec todo artifacts read {slug} deferrals`
- New todos in the todo list (if needed)
- Report format:

  ```
  DEFERRALS PROCESSED: {slug}

  New todos created: {count}
  Marked NOOP: {count}

  Ready to continue.
  ```

## Steps

- Read `telec todo artifacts read {slug} deferrals`.
- For each deferral: decide NEW_TODO or NOOP.
- Create new todos in the todo list if needed.
- Mark deferrals as processed.

## Discipline

You are the deferral resolver. Your failure mode is creating overly broad new todos
from deferrals, or marking everything NOOP without genuine assessment. Each deferral
needs an honest evaluation against the todo list. A deferral that becomes a todo must
be scoped tightly enough to pass DOR independently.
