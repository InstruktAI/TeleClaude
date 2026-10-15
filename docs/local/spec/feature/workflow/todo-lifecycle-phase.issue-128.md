---
description: 'Canonical lifecycle_phase pointer naming where a todo stands in its journey, written by the acts of the lifecycle machine and read the same way by every consumer. No operator override or manual realignment surfaces.'
visibility: 'public'
---

# Todo Lifecycle Phase — Spec

## Required reads

- docs/global/sdlc/principle/domain-driven-design.md
- docs/global/sdlc/spec/domain-spec.md
- @docs/local/spec/domain/workflow.md

## What it is

`lifecycle_phase` is the canonical pointer a todo carries to name where it stands in its journey, from preparation to
delivered. It is one validated enum value per todo, owned by the workflow context, and read by every state machine,
every CLI render and every routing decision the workflow makes. For an item driven by the lifecycle machine the machine
writes the pointer in the same transaction as the act that moves the item (`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`):
the pointer is recorded by acts, never inferred from the artifacts present. Its values are the item phases of that spec -
`preparation`, `waiting`, `prepared`, `work`, `ready` and `delivered` - and the task lane's `task_plan_drafting` and
`task_running`. The creative lane adds one reading over these: while a todo's creative state is not complete, an undelivered todo that is
not in the task lane reads as `design` whatever its stored phase. Once its design is complete, its stored phase is read
by the reading table as usual (an ordinary pre-vocabulary value reads as `preparation`, and later work or readiness
reads as it stands). `design` is a phase the creative lane's own machine drives, not one the lifecycle machine writes or
stores.

The task lane's phases are owned by the task lane, not by the lifecycle machine. `task_plan_drafting` holds a kind=`task`
todo from kind assignment or task creation until `sdlc/procedure/lifecycle/task/prepare-task` writes a `task-plan`; the
phase then advances to `prepared`, awaiting human authorization. `task_running` is the live execution marker while
`sdlc/procedure/lifecycle/task/run-task` is dispatched by the lifecycle runner; it is not a work phase and does not
satisfy the lifecycle machine's work gates.

A stored value from before this vocabulary is read as the phase the reading table of the item-lifecycle spec gives, and
the stored value is replaced at the item's next phase write. A stored value that is empty or outside the enum is an error
naming the todo and the offending raw value; the calling machine treats the todo as invalid rather than guessing a phase.
The pointer is the single source of truth for where a todo is, right now.

## Canonical fields

### Use cases

#### UC-TLP1: Kind update re-routes lifecycle_phase before work

```gherkin
Given an active todo whose work has not started
When the operator runs "telec todo update my-todo --kind bug --force"
Then the workflow service validates the target kind
And resolves the target entry point through KIND_ENTRY_PHASE
And persists lifecycle_phase to that target entry phase through the validated state-write boundary
And any invalid old-kind artifacts are warned about or handled according to the force artifact-migration contract
```

```gherkin
Given an active todo whose work has started
When the operator runs "telec todo update my-todo --kind task"
Then the workflow service refuses before changing lifecycle_phase or kind
And the current lifecycle_phase remains unchanged
```

#### UC-TLP2: Delivery evidence derives the terminal lifecycle phase

```gherkin
Given an active todo has completed its implementation lifecycle
When a lifecycle caller persists that todo's delivered status and delivery evidence
Then the workflow service writes lifecycle_phase as delivered through its validated state-write boundary
And every later reader observes delivered as the canonical phase
And no caller bypasses the write by manually overriding the pointer
```

#### UC-TLP3: A phase is written by the act that moves the item

```gherkin
Given a todo driven by the lifecycle machine
When its driver performs the prepared act, the waiting act, the kickback act or the stamp act
Then the phase that act leads to is written in the same transaction as the act
And no reader derives a different phase from the artifacts present
```

#### UC-TLP4: An unfinished design reads as design

```gherkin
Given an undelivered todo outside the task lane whose creative state is not complete
When any caller reads its phase
Then it reads as design whatever phase is stored
And once the creative state is complete its stored phase is read by the reading table as usual
And a delivered todo, and a todo in the task lane, never read as design
```

#### UC-TLP5: A phase from before the vocabulary is read in it

```gherkin
Given a persisted todo carries a lifecycle_phase value from before the item vocabulary
When state is read
Then the read returns the phase the reading table of the item-lifecycle spec gives
And the persisted value stays unchanged until the next phase write replaces it
```

#### UC-TLP6: An invalid persisted phase is an error

```gherkin
Given a todo whose stored lifecycle_phase is the empty string or a value not in the enum
When the workflow service is asked for the canonical phase
Then it raises an error naming the todo and the offending raw value
And the calling machine treats the todo as invalid rather than guessing a phase
```

### Cross-context references

- `agent_runtime` - worker dispatch reads the canonical phase to decide which driver procedure to run for a todo.
  Workers never re-derive the phase; they trust the pointer.

## Known caveats

- The canonical lifecycle is forward under normal progression: preparation, prepared, work, ready, delivered. The
  bounded returns are acts: a kickback returns an item in work to preparation, a decision resumes the phase an item
  waited in, and a stamp the integration head has moved past reads the item as work again.
- An invalid persisted `lifecycle_phase` is a hard error, not a default. The platform refuses to guess a phase for a
  todo whose pointer is missing or unrecognized.

## See Also

- docs/local/adr/0021-remove-reconcile-and-mark-phase.md — why the manual realignment and override surfaces were removed.
