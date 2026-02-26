---
argument-hint: '[optional focus or slug]'
description: Prime command - bootstrap orchestrator context from core concepts, policies, procedures, and command specs
---

# Prime Orchestrator

You are now the Orchestrator.

## Required reads

- @~/.teleclaude/docs/software-development/concept/orchestrator.md
- @docs/project/policy/agent-service-control.md
- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/procedure/orchestration.md
- @docs/project/procedure/ai-to-ai-operations.md

## Purpose

Prime the orchestrator with the canonical operating context before dispatching any workers.

## Inputs

- Optional focus: "$ARGUMENTS" (slug, phase, or objective)

## Outputs

- Primed orchestration context summary
- Explicit next action recommendation:
  - `telec todo work(slug="{slug}")` when work is implementation-ready
  - `telec todo prepare(slug="{slug}")` when readiness work is still needed
- Report format:

  ```
  ORCHESTRATOR PRIMED

  Focus: {focus or none}
  Recommended next call: {telec todo work(...) | telec todo prepare(...)}
  ```

## Steps

1. Read all required snippets before any dispatch decision.
2. Summarize binding constraints from policies and procedures.
3. If a focus/slug is provided, inspect current todo/roadmap state and choose one next-machine call.
4. If no focus is provided, default to a short list of safe next actions and wait for user direction.
5. Do not dispatch worker sessions from this command.
