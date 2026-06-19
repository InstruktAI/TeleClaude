---
description: 'Todo creation — `telec todo create <slug> <content> [--kind <kind>]` is the single creation command (content required; kind optional — a kind-less dump is classified by /analyze-todo-input), and `telec todo design` enters the creative state machine. The workflow service emits `workflow.todo.created` consumed by the lifecycle router.'
visibility: 'public'
---

# Workflow Todo Creation — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The Todo aggregate inside the `workflow` bounded context is created through one CLI entrypoint that calls a single server-side route, plus a creative-machine entrypoint that does not itself create todo entries:

- **`telec todo create <slug> <content> [--kind <kind>]`** — the single creation command. Both `<slug>` and `<content>` are required positionals; an empty or whitespace-only `<content>` is rejected before any request is made. `--kind` is optional. The workflow service writes the todo entry, the default state, and an artifact in one transaction. Flags:
  - `--kind <kind>` — **optional**. Canonical kind value: `feature` (PRD/intake lane), `change` (plan lane; no PRD), `bug` (diagnosis → plan lane), or `task` (non-SDLC action lane; created silent, grooms a `task-plan`). Omitting it creates a **kind-less** todo: the content is stored as `input`, the todo is persisted with `kind` unset and no `lifecycle_phase`, and `/analyze-todo-input` is dispatched to classify it and assign a kind autonomously via `telec todo stamp --kind-assign <kind>`. The classifier assigns the kind directly — there is no proposal and no human approval gate — then routes to that kind's entry phase. It never executes the work itself.
  <!-- planned-change:revise-todo-create-flags -->
  - `--silent` — sets `silent=True` on the request. The route still creates the todo and still emits `workflow.todo.created`, but with `pickup_requested=false` and `creation_mode="silent"`, so the lifecycle router skips dispatch.
    <!-- change:revise-todo-create-flags -->
    <!-- /planned-change:revise-todo-create-flags -->
    <!-- planned:revise-todo-create-flags -->
  - `--icebox` — creates the todo directly in the icebox (roadmap `status="icebox"`) instead of `active`. The lifecycle runner skips iceboxed entries, so no session is dispatched; the todo's kind, state, and `input` artifact are written normally, and unfreezing it later returns it to `active` and starts its lane. It is the only flag that parks a new todo instead of letting it enter its lifecycle.
  - `--project-root <path>` (alias `-p`) — targets an explicit project root instead of the invocation cwd. The path resolves the project's workflow state root server-side, and the `workflow.todo.created` payload's `project_path` reflects it so the lifecycle runner acts against the targeted project.
  - `--group <parent-slug>` — attaches the new todo as a child of `<parent-slug>` by setting its `group_slug`. The child is created complete (content + kind + state + `input` artifact) in one call; `<parent-slug>` becomes a structural holder purely through the existing child-derived predicate (a row is a holder when at least one live child group-references it) — no holder row is mutated, and the holder's own non-`input` payload is stripped at create time by the same holder-purge the split path uses. This makes `create --group` the atomic, fully-formed alternative to `telec todo split`, which scaffolds skeleton children.
  <!-- /planned:revise-todo-create-flags -->
  - `--after <slugs>` — comma-separated dependency slugs (trimmed; empties dropped); validated against the todo list at insert time.
  <!-- planned:task-lane -->
  - `--schedule <iso-instant | recurring-rule>` — valid only for `--kind task`. It records the task's execution eligibility: a one-shot ISO-8601 instant, or a recurring rule that re-fires the task against its durable `task-plan` on each occurrence. It is mutually exclusive with `--after`; the workflow service rejects a create request that supplies both.
    <!-- /planned:task-lane -->
    <!-- planned-change:plan-flag-enters-plan-draft -->
  - `--plan` — valid only with `--kind change`. The supplied content is a complete implementation plan, so the route writes the `implementation-plan` artifact and marks the todo prepared for work.
  <!-- change:plan-flag-enters-plan-draft -->
  - `--plan` — valid only with `--kind change`. The supplied content is a complete implementation plan, so the route writes it as the `implementation-plan` artifact and enters prepare at plan-drafting. The planner grounds the supplied plan (blast radius), reflects the affected doc snippets, and the plan is reviewed before `prepared`; the flag accelerates drafting, it does not bypass plan-draft or plan-review.
  <!-- /planned-change:plan-flag-enters-plan-draft -->

- **`telec todo design [<slug>]`** (and the deprecated alias `co-create`) — runs the creative state machine. It does not create a todo entry on its own; it inspects creative state for the slug (or auto-selects the next creative work item from the todo list) and returns the next-action instruction. Todo scaffolding for design work happens upstream through `create`.

The Todo aggregate's invariants — unique kebab-case slug, kind fixed once assigned, `after` dependencies validated against the todo list — are enforced before the entry is written. The workflow service is the single emission point for `workflow.todo.created`.

## Canonical fields

### `workflow.todo.created` payload (partial shape)

The workflow service emits the event with this payload:

- `slug` — the created slug.
- `kind` — canonical kind from the request: `feature`, `change`, `bug`, `task`, or `null` when the todo was created kind-less (routed to `/analyze-todo-input`).
<!-- planned-change:revise-todo-create-flags -->
- `creation_mode` — `"silent"` when the request had `silent=True`, otherwise `"pickup"`.
- `pickup_requested` — boolean, false when the caller passed `--silent` or the kind is `task`.
<!-- change:revise-todo-create-flags -->
- `creation_mode` — `"pickup"` when pickup is requested, otherwise `"silent"`; derived from `pickup_requested`.
- `pickup_requested` — boolean, false when the caller passed `--icebox` or the kind is `task`.
  <!-- /planned-change:revise-todo-create-flags -->
  <!-- planned-change:plan-flag-enters-plan-draft -->
- `lifecycle_phase` — the post-write `lifecycle_phase` value (`null` for kind-less creation, `"prepared"` for `task` and `--plan`, `"diagnose"` for `bug`, `"draft"` otherwise).
<!-- change:plan-flag-enters-plan-draft -->
- `lifecycle_phase` — the post-write `lifecycle_phase` value (`null` for kind-less creation, `"prepared"` for `task`, `"plan_drafting"` for `--plan`, `"diagnose"` for `bug`, `"draft"` otherwise).
  <!-- /planned-change:plan-flag-enters-plan-draft -->
    <!-- planned:task-lane -->
  Task creation emits `"task_plan_drafting"`.
    <!-- /planned:task-lane -->
- `created_at` — UTC ISO-8601 timestamp.
- `project_path` — effective cwd used to resolve the project's workflow state.
<!-- planned:human-lineage-on-todos -->
- `created_by_principal` — the resolved principal of the creating caller (`human:<email>` or `system:<session_id>`), read from the roadmap row's persisted owner.
  <!-- /planned:human-lineage-on-todos -->
  <!-- planned:task-lane -->
- `schedule` — optional task execution eligibility: a one-shot ISO-8601 instant or a recurring rule; omitted otherwise.
<!-- /planned:task-lane -->

### Use cases

```
Given a human or agent has a substantive idea written up
When they run `telec todo create my-feature "<content>" --kind feature`
Then the CLI validates that <content> is non-empty and the provided --kind value is canonical
And submits a creation request with kind="feature"
And the workflow service creates the todo entry, default state, and an `input` artifact whose body is "# my-feature — Input\n\n<content>\n" in one transaction
And the workflow service emits workflow.todo.created with kind="feature" and pickup_requested=true
And the lifecycle router consumes the event and dispatches /next-prepare
And the CLI reports "Created todo: my-feature"
```

<!-- planned-change:revise-todo-create-flags -->

```
Given a human is still iterating and does not want orchestrator pickup yet
When they run `telec todo create my-feature "<content>" --kind feature --silent`
Then the request carries kind="feature", silent=True
And the route still writes state + roadmap + `input` artifact identically to the default path
And the route emits workflow.todo.created with pickup_requested=false and creation_mode="silent"
And the lifecycle router observes pickup_requested=false and logs "skipped: pickup_requested=False" without dispatching
And the todo waits silently until a human invokes the next action
```

<!-- change:revise-todo-create-flags -->
<!-- /planned-change:revise-todo-create-flags -->

<!-- planned:revise-todo-create-flags -->

```
Given an operator knows an idea is parked and should not enter the lifecycle yet
When they run `telec todo create parked-idea "<content>" --kind change --icebox`
Then the request carries kind="change" and icebox=True
And the route writes state + `input` artifact with the roadmap entry's status set to "icebox"
And the route emits workflow.todo.created with pickup_requested=false
And the lifecycle runner skips the iceboxed slug and spawns no session
And the todo waits in the icebox until `telec todo unfreeze parked-idea` returns it to active
```

```
Given an operator wants to create a child of an existing parent in one call
When they run `telec todo create child-a "<content>" --kind change --group parent-slug`
Then the request carries kind="change" and group="parent-slug"
And the route writes "child-a"'s state + `input` artifact with the roadmap entry's group_slug set to "parent-slug"
And the same write strips "parent-slug" to a structural holder (its non-input state and artifacts are purged, its frozen input retained)
And "parent-slug" resolves as a holder via the live child group-reference, with no holder row mutated
And the route emits workflow.todo.created for "child-a" so its own lane proceeds under the normal dependency gate
```

<!-- /planned:revise-todo-create-flags -->

<!-- planned-change:plan-flag-enters-plan-draft -->

```
Given a human or agent already has a complete implementation plan
When they run `telec todo create my-feature "<content>" --kind change --plan`
Then the request carries kind="change" and plan=true
And the route writes the content as the `implementation-plan` artifact (body prefixed "# my-feature — Implementation Plan")
And the route applies the prepared-state primitives so lifecycle_phase becomes "prepared"
And the route emits workflow.todo.created with canonical kind="change" and pickup_requested=true
And the lifecycle router dispatches /next-work (build), bypassing prepare
And the CLI prints "Created todo: my-feature (kind=change)"
```

<!-- change:plan-flag-enters-plan-draft -->

```
Given a human or agent already has a complete implementation plan
When they run `telec todo create my-feature "<content>" --kind change --plan`
Then the request carries kind="change" and plan=true
And the route writes the content as the `implementation-plan` artifact (body prefixed "# my-feature — Implementation Plan")
And the route seeds the prepare lifecycle at plan-drafting so lifecycle_phase becomes "plan_drafting"
And the route emits workflow.todo.created with canonical kind="change" and pickup_requested=true
And the lifecycle router dispatches /next-prepare, where the planner grounds the supplied plan, reflects affected doc snippets, and the plan is reviewed before prepared
And the CLI prints "Created todo: my-feature (kind=change)"
```

<!-- /planned-change:plan-flag-enters-plan-draft -->

```
Given an operator runs `telec todo create existing-slug "<content>" --kind feature`
When the workflow service reads existing state and finds it present
Then it rejects with a conflict error "Todo 'existing-slug' already exists" and no rows are written
And no event is emitted
```

```
Given an operator runs `telec todo create my-feature "" --kind feature` (or with only whitespace)
When the CLI parses the positional arguments
Then it reports "Error: <content> is required and must not be empty" and exits non-zero
And no creation request is made
```

#### UC-WTC5: Kind-less create dispatches analyzer

```
Given a human dumps raw intent and omits `--kind`
When the CLI parses the flags
Then it submits a creation request with no kind (kind-less)
And the workflow service creates the todo, stores the dump as the `input` artifact, sets kind=null and leaves lifecycle_phase absent
And the workflow service emits workflow.todo.created with kind=null, lifecycle_phase=null, and pickup_requested=true
And the lifecycle router dispatches /analyze-todo-input, which classifies the dump and assigns the kind autonomously with `telec todo stamp --kind-assign <kind>` without executing any work
And the assignment fixes the kind exactly once and routes the todo to that kind's entry phase, with no human approval gate in between
```

```
Given a human (or an agent on their behalf) wants to park agreed future work that need not touch the codebase
When they run `telec todo create call-supplier-api "<what to do, when, and any waits>" --kind task`
Then the request carries kind="task" and is created silent (pickup_requested=false)
And the workflow service writes state + `input`, sets lifecycle_phase="prepared", and emits workflow.todo.created with kind="task" and pickup_requested=false
And the lifecycle router does not auto-dispatch; the task waits durably until a human or a dependency/time trigger starts it
And when worked, an agent grooms the `task-plan` (ticking off steps, appending results) rather than producing a code commit
```

<!-- planned:task-lane -->

#### UC-WTC6: Task create enters task-plan drafting

```gherkin
Given a human or agent creates a task with substantive input
When they run `telec todo create call-supplier-api "<what to do>" --kind task`
Then workflow writes the roadmap row, Todo state, and `input` artifact atomically
And sets kind="task" and lifecycle_phase="task_plan_drafting"
And emits `workflow.todo.created` with kind="task", lifecycle_phase="task_plan_drafting", and project identity
And the lifecycle runner may dispatch `/next-prepare-task`
And the task cannot dispatch `/next-run-task` until a `task-plan` exists and the human authorization stamp is present
```

#### UC-WTC7: Task schedule and dependencies are mutually exclusive

```gherkin
Given a caller creates a task
When the request supplies both `--after parent` and `--schedule <iso-instant>`
Then workflow rejects the request before writing roadmap, state, artifact, or event rows
And the diagnostic names the mutually exclusive fields
```

```gherkin
Given a caller creates a task with `--schedule <iso-instant>`
When the create request is accepted
Then the task has no dependency edges
And the schedule is persisted as the task execution eligibility
And the task still requires a prepared `task-plan` and human authorization before runner dispatch
```

<!-- /planned:task-lane -->

```
Given an operator runs `telec todo design my-feature`
When the workflow service is asked for the creative state for the slug
Then it returns one of: DESIGN_DISCOVERY_REQUIRED, DESIGN_SPEC_PENDING_CONFIRMATION, ART_PENDING_APPROVAL, or the next creative phase instruction
And no todo entry mutation happens for slugs that already exist; design only orchestrates creative phases
```

```
Given a customer-support agent files a bug via "telec bugs report '<description>'"
When the workflow service handles the bug creation with kind="bug"
Then it writes state + todo entry + `input` artifact and enters the diagnose phase
And the workflow service emits workflow.todo.created with canonical kind="bug" and pickup_requested=true
And the lifecycle router consumes the event and dispatches /next-prepare for the bug lane (diagnosis → plan → plan-review)
And the bug skips the demo phase per the kind=bug lifecycle gate
```

<!-- planned:human-lineage-on-todos -->

```
Given a human creates a todo via `telec todo create my-change "<content>" --kind change`
When the workflow service writes the roadmap row
Then the row's `created_by_principal` records the creating human as `human:<email>`
And `created_by_principal` is recoverable from the todo record for later audit
And the emitted `workflow.todo.created` payload carries the same `created_by_principal`
```

```
Given an agent session whose own resolved principal is `human:<root-email>` creates a todo
When the workflow service writes the roadmap row
Then `created_by_principal` records `human:<root-email>` — the chain-root human, not the agent session id
```

```
Given a todo whose `created_by_principal` is `human:<email>`
When the lifecycle runner auto-dispatches work for that todo
Then the dispatched session's resolved principal is `human:<email>`, not `system:<session_id>`
And the orchestrator → worker → integrator chain shares that one human root
And the dispatched session's authorization is unchanged — lineage is audit-only
```

<!-- /planned:human-lineage-on-todos -->

### Dependency gate at create-time

Create-time dispatch is dependency-gated by the lane selected from the creation event. The executable scenarios are `UC-WTC2` and `UC-WTC3`.

### Use cases

#### UC-WTC1: Create help exposes canonical kind choices

```gherkin
Given an operator needs to create a todo
When they run `telec todo create --help`
Then the usage line shows `--kind` as optional with values `feature|change|bug|task`
And the help states that omitting `--kind` creates a kind-less todo classified by `/analyze-todo-input`
And the help does not advertise retired kind values
```

#### UC-WTC2: Dep-blocked create event is consumed without prepare dispatch

```gherkin
Given a human runs `telec todo create child "<content>" --kind change --after parent` while "parent" has not yet reached PREPARED
When the workflow service creates "child" and emits workflow.todo.created with pickup_requested=true
And the lifecycle router consumes the event
Then the router consults the dependency graph and finds "child"'s prepare gate unsatisfied (parent not PREPARED)
And the router treats the dep-blocked child as silent — it does not dispatch /next-prepare for "child"
And the router logs "skipped: dependency-blocked" with the unsatisfied parent slug
And "child" waits until "parent" reaches PREPARED, at which point auto-continue dispatches it (see @spec/feature/workflow/prepare-state-machine)
```

#### UC-WTC3: Deps-satisfied create event dispatches prepare

```gherkin
Given a human runs `telec todo create child "<content>" --kind change --after parent` while "parent" is already PREPARED
When the lifecycle router consumes workflow.todo.created for "child"
Then the router finds "child"'s prepare gate satisfied
And the router dispatches /next-prepare for "child" as usual
```

### Cross-context references

- `operations` — async, receipt-backed long-running operations (e.g., `telec todo remove`) are surfaced through the operations subsystem; create itself is synchronous.
- `integration` — the lifecycle router cartridge consumes `workflow.todo.created` and dispatches cartridge-appropriate orchestrators (`/next-prepare`, `/next-work`).
- `agent_runtime` — the creative state machine driven by `telec todo design` spawns and supervises creative sessions through `agent_runtime`.

## Known caveats

- `<content>` is a required positional on `telec todo create`. Empty or whitespace-only content is rejected by the CLI before any request; the workflow service also rejects it as a second line of defense.
<!-- planned-change:plan-flag-enters-plan-draft -->
- `--kind` is **optional** on `telec todo create`. The valid kinds are `feature`, `change`, `bug`, and `task`. Omitting it creates a kind-less todo (kind unset, no `lifecycle_phase`) whose `input` is classified by `/analyze-todo-input`, which assigns a kind autonomously via `telec todo stamp --kind-assign <kind>` (no proposal, no human approval gate — it never executes the work). `task` is created silent and carries a living `task-plan` artifact. Use `--plan` with `--kind change` when the content is a complete implementation plan and should skip prepare.
<!-- change:plan-flag-enters-plan-draft -->
- `--kind` is **optional** on `telec todo create`. The valid kinds are `feature`, `change`, `bug`, and `task`. Omitting it creates a kind-less todo (kind unset, no `lifecycle_phase`) whose `input` is classified by `/analyze-todo-input`, which assigns a kind autonomously via `telec todo stamp --kind-assign <kind>` (no proposal and no human approval gate; it never executes the work). `task` is created silent and carries a living `task-plan` artifact. Use `--plan` with `--kind change` when the content is a complete implementation plan and should seed the implementation plan into plan-drafting before plan review.
  <!-- /planned-change:plan-flag-enters-plan-draft -->
  <!-- planned-change:revise-todo-create-flags -->
- `--silent` does NOT suppress the event. The route always emits `workflow.todo.created` after a successful create. `--silent` flips `pickup_requested` to `false`, and the lifecycle router uses that field to decide whether to dispatch.
<!-- change:revise-todo-create-flags -->
- A created todo enters its kind's lifecycle; nothing holds it back at creation. `--icebox` is the only flag that parks it instead (`status="icebox"`, `pickup_requested=false`), and the lifecycle runner skips iceboxed entries. The route always emits `workflow.todo.created` after a successful create.
  <!-- /planned-change:revise-todo-create-flags -->
  <!-- planned:revise-todo-create-flags -->
- `--group <parent-slug>` is the create-time path to a grouped child; it is the atomic counterpart to `telec todo split` (which scaffolds skeleton children). It threads `group_slug` through the create transaction's existing `add_to_roadmap` call. Holder status for the parent is **derived** from the live child reference, never stored — `create --group` mutates no holder row; the same transaction strips the parent's non-`input` payload via the holder-purge the split path already uses. `--hold` and `--release` are not accepted on create.
<!-- /planned:revise-todo-create-flags -->
- The `bugs report` helper wraps the same creation path with `kind=bug`. The prior CLI-side bug-emit helper has been removed; the workflow service is now the single emission point for bug creation as well.
- The lifecycle router selects the lane from the event payload's `kind`, `lifecycle_phase`, and `pickup_requested`, then consults todo state only for dependency gating before auto-dispatch. `telec todo create` emits canonical `feature`, `change`, `bug`, or `task` kinds, or `kind=null` for a kind-less dump — which the router dispatches to `/analyze-todo-input` for classification when dependency gates allow pickup.

- **Dependency gate at create-time:** routing by `kind`/`lifecycle_phase`/`pickup_requested` selects the _lane_, but before auto-dispatching the router consults the dependency graph for the slug. A child with unsatisfied `after` dependencies for its lane (prepare lane → parents must be `PREPARED`; work lane → parents must be `delivered`, per `@spec/feature/workflow/dependency-graph`) is treated as silent: the event is still consumed but no orchestrator is dispatched. Only deps-satisfied todos auto-dispatch. This closes the create-time over-dispatch where `create parent; create child --after parent` spawned both orchestrators in parallel.

- `telec todo design` (and the deprecated `co-create` alias) is the creative state machine entrypoint. It is NOT a Todo-creation entrypoint on its own — it orchestrates creative phases (design-spec, art, visuals) against an existing slug or auto-selects from the todo list.
- The CLI's `--after` parser splits on commas after trimming; empty entries are dropped. Dependency-existence validation happens when the entry is inserted, not in the CLI.
- The `--plan` path writes content prefixed with `# <slug> — Implementation Plan\n\n` and the default path writes content prefixed with `# <slug> — Input\n\n`. Callers should not pre-add those headers in the supplied content.
<!-- planned-change:human-lineage-on-todos -->
- The `workflow.todo.created` payload's `todo_id`, `project_id`, and `created_by_principal` may not be populated by every emitter; downstream consumers fill them via serde defaults.
<!-- change:human-lineage-on-todos -->
- The `workflow.todo.created` payload's `created_by_principal` is populated from the roadmap row's persisted owner. `todo_id` and `project_id` may still not be populated by every emitter; downstream consumers fill those via serde defaults.
<!-- /planned-change:human-lineage-on-todos -->
