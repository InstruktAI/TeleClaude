---
description: 'Todo creation — `telec todo create is the single creation command, and `telec todo design` enters the creative state machine. The workflow service emits `workflow.todo.created` consumed by the lifecycle router.'
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
  - `--icebox` — creates the todo directly in the icebox (roadmap `status="icebox"`) instead of `active`. The lifecycle runner skips iceboxed entries, so no session is dispatched; the todo's kind, state, and `input` artifact are written normally, and unfreezing it later returns it to `active` and starts its lane. It is the only flag that parks a new todo instead of letting it enter its lifecycle.
  - `--project-root <path>` (alias `-p`) — targets an explicit project root instead of the invocation cwd. The path resolves the project's workflow state root server-side, and the `workflow.todo.created` payload's `project_path` reflects it so the lifecycle runner acts against the targeted project.

- `--group <parent-slug>` — attaches the new todo as a child of `<parent-slug>` by setting its `group_slug`. The child is created complete (content + kind + state + `input` artifact) in one call; `<parent-slug>` becomes a structural holder purely through the existing child-derived predicate (a row is a holder when at least one live child group-references it) — no holder row is mutated. The holder's own `todo_state` is stripped at create time, while all of its artifacts and their version history are preserved as frozen evidence, so a parent still in the prepare lane — including one carrying a PRD, architecture, or plan — can be grouped (see UC-WTC24). A parent whose `lifecycle_phase` has reached `prepared` or a work-lane phase is refused with a 409 (see UC-WTC16). `create --group` is the atomic, fully-formed way to attach a grouped child.

- `--after <slugs>` — comma-separated dependency slugs (trimmed; empties dropped); validated against the todo list at insert time.
- `--schedule <iso-instant | recurring-rule>` — valid only for `--kind task`. It records the task's execution eligibility: a one-shot ISO-8601 instant, or a recurring rule that re-fires the task against its durable `task-plan` on each occurrence. It is mutually exclusive with `--after`; the workflow service rejects a create request that supplies both.
- `--plan` — valid with `--kind change` or `--kind task`; rejected for `--kind feature` and `--kind bug`. The supplied content is the complete plan for that kind, written as the kind's plan artifact so drafting is skipped:
  - `--kind change --plan` writes the content as the `implementation-plan` artifact (prefixed `# <slug> — Implementation Plan`) and enters prepare at plan-drafting. The planner grounds the supplied plan (blast radius), reflects the affected doc snippets, and the plan is reviewed before `prepared`; the flag accelerates drafting, it does not bypass plan-draft or plan-review.
  - `--kind task --plan` writes the content as the `task-plan` artifact (prefixed `# <slug> — Task Plan`), lands the task at `prepared`, and records the `task_approved` authorization stamp up front with its `approved_digest` set to the just-written `task-plan` digest — so the task is **pre-authorized by construction** and the lifecycle runner routes it straight to `/next-run-task` once its dependency or `schedule` gate passes, with no separate human authorization. A later `task-plan` edit changes the artifact digest and leaves the recorded `approved_digest` stale, so authorization must be renewed before the runner dispatches again.

- `--hold` — **hidden specialist control.** Creates an **active** todo (roadmap `status="active"`) whose hold flag is set with `hold_audit.source=creation`, so the lifecycle router consumes the creation event without dispatch and the lifecycle runner skips the slug until the hold is released via `telec todo update <slug> --release`. Unlike `--icebox` it does not park the todo in the icebox: the todo carries normal state and its `input` artifact, and stays visible as an active held row. It is mutually exclusive with `--icebox`. It is reserved for live-human prepare orchestration (a human driving an agent to own a new todo's prepare phase). Hidden-ness is a property of the structured flag surfaces: it is suppressed from the usage line, the Options table, and generated command tables, while the create Notes explain it as the create-time parking flag for todos fleshed out progressively.

- `--human-involved` — valid only for agent-session callers (the `agent` door); a human door derives involvement and ignores the flag. It is the filing agent's declaration that a human was in the conversation that produced the filing — saw it, asked for it, or shaped it. Omitting it records `human_involved=false`, deliberately: a forgotten flag lands the todo in the human's agent-initiated audit bucket rather than hiding an autonomous filing.

- **`telec todo design [<slug>]`** (and the deprecated alias `co-create`) — runs the creative state machine. It does not create a todo entry on its own; it inspects creative state for the slug (or auto-selects the next creative work item from the todo list) and returns the next-action instruction. Todo scaffolding for design work happens upstream through `create`.

The Todo aggregate's invariants — unique kebab-case slug, kind fixed once assigned, `after` dependencies validated against the todo list — are enforced before the entry is written. The workflow service is the single emission point for `workflow.todo.created`.

## Canonical fields

### `workflow.todo.created` payload (partial shape)

The workflow service emits the event with this payload:

- `slug` — the created slug.
- `kind` — canonical kind from the request: `feature`, `change`, `bug`, `task`, or `null` when the todo was created kind-less (routed to `/analyze-todo-input`).
- `creation_mode` — `"pickup"` when pickup is requested, otherwise `"silent"`; derived from `pickup_requested`.
- `pickup_requested` — boolean, false when the caller passed `--icebox` or the kind is `task`.
- `lifecycle_phase` — the post-write `lifecycle_phase` value (`null` for kind-less creation, `"task_plan_drafting"` for a bare `--kind task`, `"prepared"` for `--kind task --plan`, `"plan_drafting"` for `--kind change --plan`, `"diagnose"` for `bug`, `"draft"` otherwise).
- `created_at` — UTC ISO-8601 timestamp.
- `project_path` — effective cwd used to resolve the project's workflow state.

- `lineage` — the complete creation lineage in one value: the chain-root authority plus, when an agent session was the hands, that acting session. A direct human filing carries the human root alone; an agent filing under human lineage carries both the human root and the acting session in the same value; a root with no human is legitimate only for a job-runner filing. The human root is denormalized in the value so it stays resolvable after the acting session is garbage-collected. Never null: a create whose caller identity resolves to neither a human nor a session fails loudly.
- `entry_point` — the creation door, stamped mechanically by the door itself: `tui`, `cli`, `web`, `agent`, or `split`. Never declared by the caller. A todo created while an agent processes deferrals records `agent` like any other agent filing — the door records how the todo came into existence, not which todo preceded it.
- `human_involved` — boolean. Derived `true` for the human doors (`tui`, `cli`, `web`). For the `agent` door it defaults to `false`; `--human-involved` is the filing agent's declaration that a human was in the conversation that produced the filing — saw it, asked for it, or shaped it.
- `context` — door-specific reference data, never identity: the parent todo slug for the `split` door, derived from its `--group` signal; absent for every other door.

- `schedule` — optional task execution eligibility: a one-shot ISO-8601 instant or a recurring rule; omitted otherwise.

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

#### UC-WTC11: Icebox create parks the todo and suppresses dispatch

```
Given an operator knows an idea is parked and should not enter the lifecycle yet
When they run `telec todo create parked-idea "<content>" --kind change --icebox`
Then the request carries kind="change" and icebox=True
And the route writes state + `input` artifact with the roadmap entry's status set to "icebox"
And the route emits workflow.todo.created with pickup_requested=false
And the lifecycle runner skips the iceboxed slug and spawns no session
And the todo waits in the icebox until `telec todo unfreeze parked-idea` returns it to active
```

#### UC-WTC18: Held create writes active held state and exposes it through todo state views

```
Given a live-human prepare orchestrator needs to own a new todo before the runner can claim it
When they run `telec todo create held-change "<content>" --kind change --hold`
Then the request carries kind="change" and hold=True
And the route writes the roadmap entry with status="active", the default state, and the `input` artifact
And the persisted state has hold=True and hold_audit.source="creation"
And `telec todo show held-change` exposes the held state and its hold_audit.source
And `telec todo list` projects the same active row as held, reusing the existing hold projection that update-created holds use
```

#### UC-WTC19: Held create suppresses auto dispatch until release

```
Given a todo is created with `telec todo create held-change "<content>" --kind change --hold`
When the route emits workflow.todo.created
Then the payload carries pickup_requested=false
And the lifecycle router consumes the event without dispatching a session
And the lifecycle runner skips the active held todo as HELD
And after `telec todo update held-change --release` the active todo becomes eligible for its normal lane once other gates are satisfied
```

#### UC-WTC20: Hold and icebox are mutually exclusive at create time

```
Given a caller submits a create request carrying both hold=True and icebox=True
When the workflow service validates the request
Then the create is rejected before any roadmap row, state, `input` artifact, or `workflow.todo.created` event is written
And the diagnostic names hold and icebox as mutually exclusive
```

#### UC-WTC12: Group create attaches a child and derives the parent holder

```
Given an operator wants to create a child of an existing parent in one call, and parent-slug's lifecycle_phase has not yet reached "prepared"
When they run `telec todo create child-a "<content>" --kind change --group parent-slug`
Then the request carries kind="change" and group="parent-slug"
And the route writes "child-a"'s state + `input` artifact with the roadmap entry's group_slug set to "parent-slug"
And the same write strips "parent-slug"'s `todo_state` while preserving all of its artifacts and their version history as frozen evidence, so it becomes a structural holder whose prepared work survives intact
And "parent-slug" resolves as a holder via the live child group-reference, with no holder row mutated
And the route emits workflow.todo.created for "child-a" so its own lane proceeds under the normal dependency gate
And this applies because parent-slug's lifecycle_phase has not yet reached "prepared" — a parent at or past "prepared" is refused (see UC-WTC16)
```

#### UC-WTC15: Holder artifacts are frozen — a write to a holder is refused with a clean 409

```
Given "parent-slug" is a structural holder because a live child group-references it
When a caller attempts to write any non-`input` artifact to "parent-slug"
Then the workflow service refuses the write with a 409 conflict naming the slug as a structural holder with grouped children
And the holder's retained frozen `input` artifact is left unchanged
And the caller is directed to write to the holder's children instead
```

#### UC-WTC16: Group create is refused once the parent has reached prepared or the work lane

```
Given "parent-slug"'s lifecycle_phase has reached "prepared" or a work-lane phase (build_started, review_approved, etc.)
When an operator runs `telec todo create child-a "<content>" --kind change --group parent-slug`
Then the create is refused with a 409 naming "parent-slug" and its lifecycle_phase
And "parent-slug"'s `todo_state` and artifacts are left intact
And no roadmap row, state, or artifact is created for "child-a"
```

#### UC-WTC13: Project-root create targets an explicit project

```
Given an operator wants to create a todo against a project other than the invocation cwd
When they run `telec todo create remote-task "<content>" --kind change --project-root /path/to/other-project`
Then the CLI sends the create request with cwd resolved from the supplied project root
And the workflow service writes the todo into that project's workflow state, not the invocation cwd's
And the emitted workflow.todo.created payload's project_path reflects the targeted project root
And the lifecycle runner acts against the targeted project
```

#### UC-WTC14: Removed create-time parking flags are rejected

```
Given a caller submits a create request carrying a retired parking field — `--release` or the hidden `--silent` (or the corresponding `release`/`silent` request body field)
When the workflow service validates the request body
Then the create is rejected at the request boundary (fail-closed) rather than silently accepted
And no roadmap row, state, `input` artifact, or `workflow.todo.created` event is written
And the `hold` field is accepted (it is the hidden specialist dispatch brake — see UC-WTC18)
```

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

#### UC-WTC17: Task --plan creation seeds a pre-authorized task

```gherkin
Given a caller runs `telec todo create my-task "<task-plan-content>" --kind task --plan`
When the create request is accepted
Then workflow writes the content as the `task-plan` artifact prefixed `# my-task — Task Plan`
And the todo lands at lifecycle_phase="prepared" without dispatching `/next-prepare-task`
And workflow records a `task_approved` stamp whose `approved_digest` equals the seeded `task-plan` digest
And the lifecycle runner dispatches `/next-run-task` once the dependency or schedule gate passes, with no separate human authorization
```

```gherkin
Given a caller runs `telec todo create my-x "<content>" --plan` with `--kind feature` or `--kind bug`
When the create request is validated
Then workflow rejects it before writing roadmap, state, artifact, or event rows
And the diagnostic names `--plan` as valid only with `--kind change` or `--kind task`
```

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

#### UC-WTC8: Direct human filing records the human root alone

```gherkin
Given a human creates a todo from the TUI, a logged-in terminal, or the web frontend, with no agent session
When the workflow service writes the roadmap row
Then `lineage` records the human root alone as `human:<email>`
And `entry_point` records the door used (`tui`, `cli`, or `web`), stamped by the door itself
And `human_involved` is `true`, derived mechanically from the human door
And the emitted `workflow.todo.created` payload carries the same creation record
```

#### UC-WTC9: Agent filing records the complete lineage chain in one value

```gherkin
Given an agent session whose resolved principal is `human:<root-email>` creates a todo
When the workflow service writes the roadmap row
Then `lineage` records BOTH the chain-root human and the acting agent session in one value
And `entry_point` records `agent`
And no separate reporting-agent field exists — the acting session is a reading of the lineage chain, never a second column
```

#### UC-WTC10: Runner-dispatched session inherits the owning human

```gherkin
Given a todo whose `lineage` root is `human:<email>`
When the lifecycle runner auto-dispatches work for that todo
Then the dispatched session's resolved principal is `human:<email>`, not `system:<session_id>`
And the orchestrator → worker → integrator chain shares that one human root
And the dispatched session's authorization is unchanged — lineage is audit-only
```

#### UC-WTC21: Agent filing without the involvement flag lands in the autonomous audit bucket

```gherkin
Given an agent session files a todo without passing `--human-involved`
When the workflow service writes the roadmap row
Then `human_involved` is `false`
And the todo is projected as agent-initiated for audit (started without a human)
And a filing agent that omits the flag for a human-shaped conversation produces a false alarm, never a hidden autonomous filing
```

#### UC-WTC22: Human-involved agent filing is declared, not inferred

```gherkin
Given an agent files a todo from a conversation a human was part of — saw it, asked for it, or shaped it
When the agent passes `--human-involved` on the create or bug-report call
Then `human_involved` is recorded `true`
And `lineage` still records the full chain (human root plus acting session)
And `entry_point` remains `agent` — involvement never rewrites the door
```

#### UC-WTC23: A lineage-less create fails loudly

```gherkin
Given a create call whose caller identity resolves to neither a human nor an agent session
When the workflow service validates the request
Then the create is rejected loudly before any roadmap row, state, `input` artifact, or event is written
And the diagnostic names the unresolvable creation lineage as a contract violation
And no default, sentinel, or silent human/system fallback is recorded
```

#### UC-WTC25: A prepare split stamps its door from the grouping signal

```gherkin
Given a planner creates a grouped child with `telec todo create <child> --group <parent>`
When the workflow service writes the roadmap row
Then `entry_point` records `split`, derived from the `--group` signal rather than declared
And `context` records the parent todo's slug
And `lineage` records the chain of the acting planner session under its human root
```

#### UC-WTC26: Job-runner filing is the only legitimate no-human lineage

```gherkin
Given a job-runner session files a bug with no human at its chain root
When the workflow service writes the roadmap row
Then `lineage` records the job session's system root
And `human_involved` is `false`
And any non-job session filing without a resolvable human root is rejected per UC-WTC23
```

#### UC-WTC24: Group create succeeds against a prepare-lane parent carrying prepared artifacts

```gherkin
Given "parent-slug" is mid-plan-review, carrying `prd`, `architecture`, `implementation-plan`, and `plan-review-findings` artifacts with version history
When an operator runs `telec todo create child-a "<content>" --kind change --group parent-slug`
Then the create succeeds and "child-a" is attached with group_slug set to "parent-slug"
And "parent-slug" resolves as a structural holder via the live child group-reference
And "parent-slug"'s `todo_state` is stripped
And every artifact "parent-slug" carried survives unchanged, with its full version history, as frozen evidence
And a subsequent write or remove against "parent-slug" is refused with a 409, so the preserved evidence is read-only
```

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
And the usage line and the Options table do not advertise the hidden `--hold` flag, which the Notes are free to explain
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
- `--kind` is **optional** on `telec todo create`. The valid kinds are `feature`, `change`, `bug`, and `task`. Omitting it creates a kind-less todo (kind unset, no `lifecycle_phase`) whose `input` is classified by `/analyze-todo-input`, which assigns a kind autonomously via `telec todo stamp --kind-assign <kind>` (no proposal and no human approval gate; it never executes the work). A bare `task` is created silent and enters `task_plan_drafting`, where `/next-prepare-task` authors its `task-plan`. Use `--plan` with `--kind change` when the content is a complete implementation plan and should seed the implementation plan into plan-drafting before plan review, or with `--kind task` when the content is a complete `task-plan`: the task is born `prepared` and pre-authorized (the `task_approved` stamp is written at creation, digest-bound to the seeded `task-plan`), so the runner routes it straight to `/next-run-task` once its dependency or `schedule` gate passes.
- A created todo enters its kind's lifecycle; nothing holds it back at creation by default. Two flags suppress create-time dispatch (`pickup_requested=false`): `--icebox` parks it in the icebox (`status="icebox"`), and `--hold` leaves it **active** but sets the durable dispatch brake (`hold=True`, `hold_audit.source="creation"`). The lifecycle runner skips both — iceboxed entries by status, held entries by the hold brake — until the icebox is unfrozen or the hold is released. The two are mutually exclusive. The route always emits `workflow.todo.created` after a successful create.

- `--group <parent-slug>` is the create-time path to a grouped child. It threads `group_slug` through the create transaction's existing `add_to_todo` call. Holder status for the parent is **derived** from the live child reference, never stored — `create --group` mutates no holder row; the same transaction strips the parent's `todo_state` while preserving all of its artifacts and their version history as frozen evidence, so a parent still in the prepare lane can be grouped without shredding prepared work (see UC-WTC24). A parent whose lifecycle_phase has reached `prepared` or the work lane is refused with a 409 instead (see UC-WTC16). `--release` is not accepted on create; `--hold` is the hidden create-time dispatch brake (see UC-WTC18).

- The `bugs report` helper wraps the same creation path with `kind=bug`. The prior CLI-side bug-emit helper has been removed; the workflow service is now the single emission point for bug creation as well.
- The lifecycle router selects the lane from the event payload's `kind`, `lifecycle_phase`, and `pickup_requested`, then consults todo state only for dependency gating before auto-dispatch. `telec todo create` emits canonical `feature`, `change`, `bug`, or `task` kinds, or `kind=null` for a kind-less dump — which the router dispatches to `/analyze-todo-input` for classification when dependency gates allow pickup.

- **Dependency gate at create-time:** routing by `kind`/`lifecycle_phase`/`pickup_requested` selects the _lane_, but before auto-dispatching the router consults the dependency graph for the slug. A child with unsatisfied `after` dependencies for its lane (prepare lane → parents must be `PREPARED`; work lane → parents must be `delivered`, per `@spec/feature/workflow/dependency-graph`) is treated as silent: the event is still consumed but no orchestrator is dispatched. Only deps-satisfied todos auto-dispatch. This closes the create-time over-dispatch where `create parent; create child --after parent` spawned both orchestrators in parallel.

- `telec todo design` (and the deprecated `co-create` alias) is the creative state machine entrypoint. It is NOT a Todo-creation entrypoint on its own — it orchestrates creative phases (design-spec, art, visuals) against an existing slug or auto-selects from the todo list.
- The CLI's `--after` parser splits on commas after trimming; empty entries are dropped. Dependency-existence validation happens when the entry is inserted, not in the CLI.
- The `--plan` path writes content prefixed with `# <slug> — Implementation Plan\n\n` for `--kind change` and `# <slug> — Task Plan\n\n` for `--kind task`; the default path writes content prefixed with `# <slug> — Input\n\n`. Callers should not pre-add those headers in the supplied content.

- The `workflow.todo.created` payload's creation record (`lineage`, `entry_point`, `human_involved`, `context`) is populated from the roadmap row's persisted values. `todo_id` and `project_id` may still not be populated by every emitter; downstream consumers fill those via serde defaults.
- Answering "who created this todo" means reading the creation record — `entry_point`, `lineage`, `human_involved`, `context` — never inferring from account identity. The lineage root is the authority the work ran under, not the author of the work.
