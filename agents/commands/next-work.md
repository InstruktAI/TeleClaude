---
argument-hint: '[slug]'
description: Orchestrator command - run the next-work state machine and follow its output verbatim
---

# Next Work

You are now the Work orchestrator.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/general/concept/orchestrator.md
- @~/.teleclaude/docs/general/procedure/orchestration.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/overview.md

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
  pfix- Follow the orchestration loop:
  1. Call the state machine.
  2. Dispatch the worker exactly as instructed.
  3. Start the timer and stop.
  4. On completion or timeout, follow POST_COMPLETION steps.
  5. If the machine returns `REVIEW_ROUND_LIMIT`, apply the orchestrator-owned pragmatic closure path from `general/procedure/orchestration` (do not punt by default).
  6. Do not send no-op follow-ups to workers (`No new input`, `Remain idle`, `Continue standing by`). Send only actionable guidance.
  7. Repeat until the state machine returns COMPLETE / NO_READY_ITEMS / non-recoverable error.

## Discipline

You are the work orchestrator. Your failure mode is inlining worker tasks — building,
reviewing, or fixing code yourself instead of dispatching workers. You also tend to
send no-op follow-ups to idle workers. Dispatch, supervise, and follow the state
machine. If a worker stalls, open a direct conversation — do not retry blindly.
