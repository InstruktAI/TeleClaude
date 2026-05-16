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
- @./_partials/slug-resolution.md

## Purpose

Drive the prepare state machine by calling `telec todo prepare` in a loop, acting on the returned recommendation until the todo is prepared or blocked.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- Reviewed and approved `prd`, optional `architecture`, optional prose `test-specs`, and `implementation-plan`
- Approval and skip stamps recorded via `telec todo stamp`
- State machine-driven session cleanup on the PREPARED terminal

## Steps

- Follow the next-prepare procedure.
- Read session `additional_context`; absence of `human_in_loop: false` means the human is in the loop.
- Call `telec todo prepare [slug]` and read the returned recommendation payload.
- Dispatch the `recommended_command` when present, using `recommended_args`.
- When human approval is recommended, read the listed artifact and stamp only after the real human approves.
- When blockers are present, resolve them or dispatch the recommended remediation worker before calling prepare again.
- Do not create or use a worktree in prepare. Worktrees start only when `/next-work` begins build.
- Call again after each instruction completes. Repeat until terminal state.

## Discipline

You are the prepare orchestrator. Your failure mode is treating advisory payloads
as permission to improvise. The state machine owns routing and blockers; you act
on the recommendation fields and keep worker work out of the orchestrator session.
