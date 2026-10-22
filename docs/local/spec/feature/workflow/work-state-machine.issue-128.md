---
description: 'What `telec todo work` answers before an item reaches the item machine — a call without an item, an unknown item, a structural holder — and how the lifecycle runner executes a task.'
visibility: 'public'
---

# Work State Machine — Spec

## What it is

`telec todo work <item>` is the entry to work. For an item the item machine reads, the verb is that machine's entry verb: it starts the work driver or returns the instruction to the driver that holds the item, and on a `ready` item the integrator has not admitted it takes a stated reason (`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`, `local/projects/teleclaude/spec/feature/workflow/item-acts`). What connects the work driver and its builder, the stamp, and the integrator's periodic candidate scan that admits a ready item with or without its notice are `local/projects/teleclaude/spec/feature/workflow/work-review-cycle`. How the operation routes a request between lanes is `local/projects/teleclaude/design/architecture/next-machine`.

This spec owns what the verb answers before an item reaches the machine, and the task lane's execution. The verb is scoped to one explicit item: a call without one terminalizes and never selects unrelated work. An item that does not exist is refused without creating anything. A structural holder is never worked itself: the verb routes the caller to the holder's runnable direct children.

The item's worktree is created and prepared on demand, branched from `origin/main`, with at most one ensure-and-prepare per item at a time (`local/projects/teleclaude/spec/feature/workflow/worktree-prep-lifecycle`); which refs a session inside it may name is `local/projects/teleclaude/design/code-commit`.

Task execution is a separate non-SDLC lane. The lifecycle runner starts `sdlc/procedure/lifecycle/task/run-task <slug>` for a prepared, authorized task; the item machine does not handle task execution and does not create a worktree. `sdlc/procedure/lifecycle/task/run-task` reads and grooms `task-plan`, performs the authorized work, records results in the task-plan, and ends on a `success` firing — a recurring task is re-run as a fresh `sdlc/procedure/lifecycle/task/run-task` at its next due instant — while an `error` firing stays alive for human follow-up.

## Canonical fields

### Use cases

#### UC-WSM2: Explicit work rejects unknown slugs without creating roadmap rows

```gherkin
Given no active or iceboxed Todo exists for "unknown-work"
When the orchestrator runs "telec todo work unknown-work"
Then the work machine returns TODO_NOT_FOUND with a concrete todo-create next step
And no roadmap row is created for "unknown-work"
```

#### UC-WSM3: Bare work call terminalizes instead of selecting unrelated work

```gherkin
Given a work orchestrator has no current slug
When the orchestrator runs "telec todo work"
Then the work machine returns NO_CURRENT_WORK_SLUG
And the machine emits "telec reminders set session-departure"
And the machine does NOT select a ready todo from the roadmap
```

#### UC-WSM4: Task execution uses run-task, not Phase B build

```gherkin
Given a Todo has kind="task", lifecycle_phase="prepared", a `task-plan`, and a task authorization stamp
And the task has no schedule, or its schedule's current due instant is at or before the runner evaluation instant
When the lifecycle runner evaluates eligible work for the project
Then it starts `sdlc/procedure/lifecycle/task/run-task <slug>` without creating a worktree
And records the spawned task session as the Todo's `active_runner`
And no reservation, expiry, or other pre-ownership state participates
And records or preserves lifecycle_phase="task_running" while the task session is live
```

```gherkin
Given a task lacks authorization, lacks a `task-plan`, has a future schedule, is held, or already names a live task session as `active_runner`
When the lifecycle runner evaluates eligible work for the project
Then it does not start `sdlc/procedure/lifecycle/task/run-task`
And it leaves the SDLC work state machine untouched
```

```gherkin
Given `sdlc/procedure/lifecycle/task/run-task` reaches the end of the task-plan
When it stamps the firing outcome
Then a `success` firing ends the session — a one-shot delivers the todo, a recurring records the firing and leaves the todo live for its next instant
And an `error` firing holds the todo and stays alive as the human-inspection beacon
And it does not stamp build-complete, dispatch review, or enter finalize-ready
```

```gherkin
Given a recurring task has a live `sdlc/procedure/lifecycle/task/run-task` session and its schedule reaches a new due instant
When the lifecycle runner evaluates eligible work for the project
Then it does not start a second `sdlc/procedure/lifecycle/task/run-task`
And it does not signal the live run session
```

```gherkin
Given a recurring task has no live `sdlc/procedure/lifecycle/task/run-task` session and its schedule reaches a due instant
When the lifecycle runner evaluates eligible work for the project
Then it dispatches a fresh `sdlc/procedure/lifecycle/task/run-task`, exactly like a one-shot
```

## Known caveats

- A holder entry cannot itself enter work. The caller is always routed to the holder's direct, runnable children, through the same holder resolution preparation uses.
