---
argument-hint: '[slug]'
description: Prepare orchestrator command - drive the prepare state machine, dispatch workers, supervise
---

# Prepare

You are now the Prepare orchestrator.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md
- @docs/_snippets/slug-resolution.md

## Purpose

Drive the prepare state machine by calling `telec todo prepare` in a loop, acting on the returned recommendation until the todo is prepared or blocked.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- Reviewed and approved `prd`, optional `architecture`, optional prose `test-specs`, and `implementation-plan`
- Approval and skip stamps recorded via `telec todo stamp`
- State machine-driven session cleanup on the PREPARED terminal

## Steps

Follow the prepare overview procedure.

## Discipline

Follow the prepare overview procedure's discipline.
