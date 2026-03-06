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
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md

## Purpose

Drive the prepare state machine by calling `telec todo prepare` in a loop, dispatching workers as instructed until the todo is prepared or blocked.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- Reviewed and approved `requirements.md` and `implementation-plan.md`
- Gate verdict in `state.yaml`
- All sessions ended on completion

## Steps

- Follow the next-prepare procedure.
- Call `telec todo prepare [slug]` and execute the returned instruction.
- Call again after each instruction completes. Repeat until terminal state.
