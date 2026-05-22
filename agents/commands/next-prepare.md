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
- @docs/snippets/slug-resolution.md

## Purpose

Drive the prepare state machine by calling `telec todo prepare` in a loop, acting on the returned recommendation until the todo is prepared or blocked.

## Steps

Complete the procedure above.
