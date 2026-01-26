---
argument-hint: '[slug]'
description: Orchestrator command - run the next-work state machine and follow its output verbatim
---

# Next Work

## Required Reads

@~/.teleclaude/docs/software-development/roles/orchestrator.md
@~/.teleclaude/docs/software-development/procedure/orchestration.md
@~/.teleclaude/docs/software-development/procedure/lifecycle-overview.md

Slug given: "$ARGUMENTS"

---

## Your Task

Call `teleclaude__next_work` and follow its instructions exactly.

If a slug is provided, pass it through to `teleclaude__next_work`.
If no slug is provided, call `teleclaude__next_work` without a slug.

Execute the orchestration loop:

1. Call the state machine.
2. Dispatch the worker exactly as instructed.
3. Start the timer and stop.
4. On completion or timeout, follow POST_COMPLETION steps.
5. Repeat until the state machine returns COMPLETE / NO_READY_ITEMS / error.

## Report Completion

```
NEXT_WORK COMPLETE

Final status: [COMPLETE | NO_READY_ITEMS | ERROR]
Last slug: {slug or none}
```
