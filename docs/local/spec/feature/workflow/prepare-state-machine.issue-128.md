---
description: 'What `telec todo prepare` answers before an item reaches the item machine: a call without an item, an unknown item, a structural holder and a task.'
visibility: 'public'
---

# Prepare State Machine — Spec

## What it is

`telec todo prepare <item>` is the entry to preparation. For an item the item machine reads, the verb is that machine's entry verb: it starts the preparation driver or returns the instruction to the driver that holds the item (`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`, `local/projects/teleclaude/spec/feature/workflow/item-acts`). How the operation routes a request between lanes is `local/projects/teleclaude/design/architecture/next-machine`.

This spec owns what the verb answers before an item reaches the machine. The verb requires an explicit item and never selects one. An item that does not exist is refused without creating anything. A structural holder is never prepared itself: the verb routes the caller to the holder's runnable direct children. A todo of kind task is prepared by the task lane, not by the item machine (`sdlc/spec/todo-kind-task`).

## Canonical fields

### Explicit item required

The verb requires an explicit item. Invoked without one it returns a `TODO_SLUG_REQUIRED` error rather than resolving a candidate itself. Choosing which item enters preparation belongs to the lifecycle runner's dependency-gated dispatch (`local/projects/teleclaude/spec/feature/workflow/dependency-graph`), which always names a concrete item; the verb never auto-selects.

### Use cases

#### UC-WPS3: Slugless prepare is rejected

```gherkin
Given any todo state
When the orchestrator runs "telec todo prepare" without an explicit slug
Then the prepare state machine returns a TODO_SLUG_REQUIRED error
And it does not resolve, adopt, or dispatch any candidate
```

#### UC-WPS4: Explicit prepare rejects unknown slugs without creating roadmap rows

```gherkin
Given no active or iceboxed Todo exists for "unknown-prepare"
When the orchestrator runs "telec todo prepare unknown-prepare"
Then the prepare machine returns TODO_NOT_FOUND with a concrete todo-create next step
And no roadmap row is created for "unknown-prepare"
```

```
Given an entrypoint slug is a structural holder with direct children child-a and child-b
When the orchestrator calls "telec todo prepare holder-slug"
Then the machine resolves the runnable children and returns an instruction listing "telec todo prepare child-a" and "telec todo prepare child-b"
And the machine never writes lifecycle state for the holder
And if every direct child is already prepared or delivered, the instruction explains which terminal state the holder reached
```

#### UC-WPS6: Task todos bypass the prepare machine

```gherkin
Given a Todo has kind="task" at lifecycle_phase="task_plan_drafting"
When an operator runs `telec todo prepare my-task`
Then the prepare state machine does not own task preparation
And it routes the operator to the task lane (`sdlc/procedure/lifecycle/task/prepare-task`, dispatched by the lifecycle runner)
And it requires no PRD, architecture, implementation-plan, or reviewer verdict for the task
```

## Known caveats

- A holder entry cannot itself enter preparation. The caller is always routed to the holder's direct, runnable children — even when the holder is the explicit item argument.
