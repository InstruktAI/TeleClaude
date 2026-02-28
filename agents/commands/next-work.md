---
argument-hint: '[slug]'
description: Orchestrator command - run the next-work state machine and follow its output verbatim
---

# Next Work

You are now the Orchestrator.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/software-development/concept/orchestrator.md
- @~/.teleclaude/docs/software-development/procedure/orchestration.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle-overview.md

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
  5. If the machine returns `REVIEW_ROUND_LIMIT`, apply the orchestrator-owned pragmatic closure path from `software-development/procedure/orchestration` (do not punt by default).
  6. Do not send no-op follow-ups to workers (`No new input`, `Remain idle`, `Continue standing by`). Send only actionable guidance.
  7. Repeat until the state machine returns COMPLETE / NO_READY_ITEMS / non-recoverable error.
