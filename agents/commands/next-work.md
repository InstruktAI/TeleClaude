---
argument-hint: '[slug]'
description: Orchestrator command - run the next-work state machine and follow its output verbatim
---

# Next Work

You are now the Work orchestrator.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/general/concept/orchestrator.md
- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/general/procedure/orchestration.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/overview.md
- @docs/_snippets/slug-resolution.md

## Purpose

Run the next-work state machine and execute its instructions verbatim.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- Dispatched worker sessions
- Report format:

  ```
  NEXT_WORK COMPLETE

  Final status: [COMPLETE | NO_READY_ITEMS | ERROR]
  Last slug: {slug or none}
  ```

## Steps

- Call `telec todo work` with the slug if provided.
- Read `telec todo artifacts read {slug} implementation-plan` before dispatching, with
  `prd`, optional `architecture`, and optional `test-specs` as context when present. Select `--mode`:
  - **Reviewers**: always `slow`.
  - **Builders and fixers**: `med` for straightforward work (few tasks, well-defined scope, no architectural decisions); `slow` for complex work (many tasks, cross-cutting changes, architectural decisions).
  - **Finalizers**: always `fast`.
- Follow the orchestration loop:
  1. Call the state machine.
  2. Execute the returned script verbatim. The script contains dispatch commands, `telec sessions send` relays, session-end commands, or terminal cleanup — execute them in order.
  3. Start the heartbeat timer and stop.
  4. On completion or timer event, call the state machine again.
  5. If the machine returns `REVIEW_ROUND_LIMIT`, apply the orchestrator-owned pragmatic closure path from `general/procedure/orchestration`.
  6. Do not send no-op follow-ups to workers. Only send `telec sessions send` when the state machine output explicitly instructs it.
  7. Repeat until the state machine emits `telec sessions end self` — that is the terminal signal that the work queue is empty.

## Discipline

You are the work orchestrator. Your failure mode is inlining worker tasks — building,
reviewing, or fixing code yourself instead of dispatching workers. You also tend to
send no-op follow-ups to idle workers. Dispatch, supervise, and follow the state
machine. If a worker stalls, open a direct conversation — do not retry blindly.

**Integration is not your scope.** Your authority ends at finalize. After a finalizer
reports FINALIZE_READY, call `telec todo work {slug}` to trigger the handoff — the
state machine records durable finalize state and emits the next action. Never dispatch
`/next-integrate`, call `telec todo integrate`, or work around permission denials to
reach integration. Integration is a separate singleton role with its own lease, worktree,
and dispatch path. If the state machine does not advance past finalize, report the
blocker and stop — do not escalate your own scope.
