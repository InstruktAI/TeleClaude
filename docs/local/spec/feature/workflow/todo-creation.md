---
description: 'Todo creation — `telec todo create is the single creation command, and `telec todo design` enters the creative state machine. The workflow service emits the todo-created event consumed by the lifecycle router.'
visibility: 'public'
---

# Workflow Todo Creation — Spec

## What it is

The Todo aggregate inside the `workflow` bounded context is created through one CLI entrypoint that calls a single server-side route, and through the platform's filing of failed required CI checks, plus a creative-machine entrypoint that does not itself create todo entries:

- **`telec todo create <slug> <content> --kind <kind>`** — the single creation command. Both `<slug>` and `<content>` are required positionals; an empty or whitespace-only `<content>` is rejected before any request is made. `--kind` is required. The workflow service writes the todo entry, the default state, and an artifact in one transaction. Flags:
  - `--kind <kind>` — **required**. Canonical kind value: `feature` (PRD/intake lane), `change` (plan lane; no PRD), `bug` (diagnosis → plan lane), or `task` (non-SDLC action lane; created silent, grooms a `task-plan`). The kind maps one-to-one onto the todo's lifecycle lane from creation. A creation request without a kind is refused before anything is written, and the refusal names the four kinds. A wrong kind is corrected with `telec todo update <slug> --kind <kind>`.
  - `--icebox` — creates the todo directly in the icebox (roadmap `status="icebox"`) instead of `active`. The lifecycle runner skips iceboxed entries, so no session is dispatched; the todo's kind, state, and `input` artifact are written normally, and unfreezing it later returns it to `active` and starts its lane. It is the only flag that parks a new todo instead of letting it enter its lifecycle.
  - `--project-root <path>` (alias `-p`) — targets an explicit project root instead of the invocation cwd. The path resolves the project's workflow state root server-side, and the todo-created event payload's `project_path` reflects it so the lifecycle runner acts against the targeted project.

- `--group <parent-slug>` — attaches the new todo as a child of `<parent-slug>` by recording a group reference to the parent's durable row id. The child is created complete (content + kind + state + `input` artifact) in one call. The first grouped child transitions the parent's row to status `holder` — a one-way exit from the todo lifecycle: the parent's `todo_state` is removed, any claim or hold on it is void, and all of its artifacts and their version history are preserved as frozen evidence, so a parent still in the prepare lane — including one carrying a PRD, architecture, or plan — can be grouped (see UC-WTC24). A parent whose `lifecycle_phase` has reached `prepared` or a work-lane phase is refused, because a todo cannot exit the lifecycle mid-build (see UC-WTC16). Grouping under an existing holder attaches the child the same way, including a holder whose earlier group has ended. `create --group` is the atomic, fully-formed way to attach a grouped child. Grouping also moves the parent's pending documentation ownership to the first grouped child: every in-body marker, companion filename, and `delivered_by` membership naming the parent is rewritten to that child and committed as part of the same transition.

- `--after <slugs>` — comma-separated dependency slugs (trimmed; empties dropped); validated against the todo list at insert time.
- `--schedule <iso-instant | recurring-rule>` — valid only for `--kind task`. It records the task's execution eligibility: a one-shot ISO-8601 instant, or a recurring rule that re-fires the task against its durable `task-plan` on each occurrence. It is mutually exclusive with `--after`; the workflow service rejects a create request that supplies both.

- `--plan` — valid with `--kind change` or `--kind task`; rejected for `--kind feature` and `--kind bug`. The supplied content is the complete plan for that kind, written as the kind's plan artifact so drafting is skipped:
  - `--kind change --plan` writes the content as the `implementation-plan` artifact (prefixed `# <slug> — Implementation Plan`) and enters prepare at plan-drafting. The planner grounds the supplied plan (blast radius), reflects the affected doc snippets, and the plan is reviewed before `prepared`; the flag accelerates drafting, it does not bypass plan-draft or plan-review.
  - `--kind task --plan` writes the content as the `task-plan` artifact (prefixed `# <slug> — Task Plan`), lands the task at `prepared`, and records the `task_approved` authorization stamp up front with its `approved_digest` set to the just-written `task-plan` digest — so the task is **pre-authorized by construction** and the lifecycle runner routes it straight to `/sdlc/run-task` once its dependency or `schedule` gate passes, with no separate human authorization. A later `task-plan` edit changes the artifact digest and leaves the recorded `approved_digest` stale, so authorization must be renewed before the runner dispatches again.

- `--hold` — **hidden specialist control.** Creates an **active** todo (roadmap `status="active"`) whose hold flag is set with `hold_audit.source=creation`, so the lifecycle router consumes the creation event without dispatch and the lifecycle runner skips the slug until the hold is released via `telec todo update <slug> --release`. Unlike `--icebox` it does not park the todo in the icebox: the todo carries normal state and its `input` artifact, and stays visible as an active held row. It is mutually exclusive with `--icebox`. It is reserved for live-human prepare orchestration (a human driving an agent to own a new todo's prepare phase). Hidden-ness is a property of the structured flag surfaces: it is suppressed from the usage line, the Options table, and generated command tables, while the create Notes explain it as the create-time parking flag for todos fleshed out progressively.

- `--human-involved <reason>` — valid only for agent-session callers (the `agent` door); a human door derives involvement and ignores the flag. The reason must be non-empty; a missing or blank reason is refused as argument validation. The recorded value is resolved from the acting session's latest authenticated human input: inside the code-owned recency window it records `true`, outside it records `false` and the creation proceeds unchanged. The reason remains only in the invoking session's transcript and is never written to the todo, its artifacts, events, logs, output, or UI. Omitting the flag records `human_involved=false`; the record applies only to this creation act and never propagates through its lifecycle.

- **`telec todo design [<slug>]`** — runs the creative state machine. It does not create a todo entry on its own; it inspects creative state for the slug (or auto-selects the next creative work item from the todo list) and returns the next-action instruction. Todo scaffolding for design work happens upstream through `create`.

- **Failed required-check filing** — no command. The workflow's failed-check filer creates a `bug` through the same single creation transaction as `create`: the todo entry, the default state, the `input` artifact and the todo-created event. Its creation record's lineage root is the platform's system principal, with no acting session. It faces no interrogation gate, because `sdlc/policy/todo-creation-discipline` admits a failed required check's filing without one. What it files, and when it adds to an open bug instead, is `local/projects/teleclaude/spec/feature/workflow/failed-check-bugs`.

The Todo aggregate's invariants — unique kebab-case slug, a canonical kind present from creation, `after` dependencies validated against the todo list — are enforced before the entry is written. The workflow service is the single emission point for the todo-created event.

## Canonical fields

### Filing under a receipt

A filing through `telec todo create`, `telec bugs report` or the TUI is answered
in two steps.

The request itself checks everything it can answer without the shared git lock
or the project's workflow store write: the slug, dependency and group formats,
non-empty content, the schedule, plan and hold rules, a live todo already
holding the slug, the creation lineage, and the involvement record resolved
from the human's presence at that moment. A request failing one of these is
refused with its diagnostic and nothing is filed.

A request passing them returns a durable operation receipt
(`local/projects/teleclaude/design/architecture/operation-receipts`), and the
filing runs after the response: the documentation evidence check, the todo
entry with its first artifact, plan or task seeding, and the todo-created
event. Its outcome is delivered to the filing session. A created todo's outcome
names it and carries any dependency warnings; a refused filing's outcome carries
the refusal's diagnostic, and nothing of it was created. The command line prints
the receipt and returns without waiting.

Filings of one project complete in the order their requests were accepted. A
filing starts only once every filing that project accepted before it has ended,
created or refused, so a todo filed with `--after` or `--group` naming a todo
filed just before it finds that todo created.

### Reviewed documentation evidence

Before creation admits work that declares pending documentation into its
lifecycle, the owning boundary verifies the documentation evidence required by
`sdlc/policy/todo-creation-discipline`. It resolves the intended slug's associated
documentation commits from both inferred footer names under
`general/policy/commits`, checks repository-owned independent review verdicts for
the referenced revisions, and confirms that the pending documentation entering
the lifecycle matches the reviewed content. Evidence survives without an
existing todo and without a current session claim.

Every declared pending document is covered by a matching footer-associated
commit. A missing association blocks entry even when the associated-commit
lookup returns no commits; it does not classify the work as having no
documentation delta. Independent approval is established from the verified
stamp and producing-session provenance required by `general/policy/commits`.

For first-child grouping, the admission inventory includes the parent's pending
documents that the grouping operation transfers to the child. The parent's
associated reviewed revision covers the transferred contract only through
workflow-owned evidence binding that revision to the exact pending-identity
rewrite and its resulting paths and content. That evidence persists with the
successful grouping, including parked children, and remains available when the
child enters the lifecycle. It supplies association continuity, never a review
verdict. Content outside that exact transformation requires its own current
associated independent approval under `sdlc/policy/todo-creation-discipline`.

Refusal precedes todo state, artifact creation and dispatch, and identifies the
missing, stale or unresolved evidence with its commit reference and the existing
review path. A transcript assertion, an author's discard, or the creation
command's `--approved` acknowledgment supplies no independent review approval.
The check keeps the existing classification of no-documentation work and the
icebox entry rules; it does not classify prose or infer documentation impact.
Unfreezing performs the same evidence check when parked work enters the
lifecycle (`general/principle/trust-and-guardrails`).

### Todo-created event payload (partial shape)

The workflow service emits the event with this payload:

- `slug` — the created slug.
- `kind` — canonical kind from the request: `feature`, `change`, `bug`, or `task`. Never null.
- `creation_mode` — `"pickup"` when pickup is requested, otherwise `"silent"`; derived from `pickup_requested`.
- `pickup_requested` — boolean, false when the caller passed `--icebox` or the kind is `task`.
- `lifecycle_phase` — the post-write `lifecycle_phase` value (`"task_plan_drafting"` for a bare `--kind task`, `"prepared"` for `--kind task --plan`, `"plan_drafting"` for `--kind change --plan`, `"diagnose"` for `bug`, `"draft"` otherwise).
- `created_at` — UTC ISO-8601 timestamp.
- `project_path` — effective cwd used to resolve the project's workflow state.

- `lineage` — the complete creation lineage in one value: the chain-root authority plus, when an agent session was the hands, that acting session. A direct human filing carries the human root alone; an agent filing under human lineage carries both the human root and the acting session in the same value; a root with no human is legitimate only for a job-runner filing or the platform's failed-check filing, which records the system daemon principal with no acting session. The human root is denormalized in the value so it stays resolvable after the acting session is garbage-collected. Never null: a create whose caller identity resolves to neither a human nor a session fails loudly.
- `entry_point` — the creation door, stamped mechanically by the door itself: `tui`, `cli`, `agent`, `split`, or `platform`, which is the platform's failed-check filing. Never declared by the caller. A todo created while an agent processes deferrals records `agent` like any other agent filing — the door records how the todo came into existence, not which todo preceded it.

- `human_involved` — boolean. Derived `true` for the human doors (`tui`, `cli`). For the `agent` door it defaults to `false` and becomes `true` only when this creation call carries a declaration and the acting session's observed human input is recent. It is never inherited from the session, lineage, parent todo, or any preceding act.
- `context` — door-specific reference data, never identity: the parent todo slug for the `split` door, derived from its `--group` signal; absent for every other door.

- `schedule` — optional task execution eligibility: a one-shot ISO-8601 instant or a recurring rule; omitted otherwise.

### Use cases

```
Given a human or agent has a substantive idea written up
When they run `telec todo create my-feature "<content>" --kind feature`
Then the CLI validates that <content> is non-empty and the provided --kind value is canonical
And submits a creation request with kind="feature"
And the workflow service creates the todo entry, default state, and an `input` artifact whose body is "# my-feature — Input\n\n<content>\n" in one transaction
And the workflow service emits the todo-created event with kind="feature" and pickup_requested=true
And the lifecycle router consumes the event and dispatches /sdlc/prepare
And the outcome delivered to the filing session names the created todo "my-feature"
```

#### UC-WTC11: Icebox create parks the todo and suppresses dispatch

```
Given an operator knows an idea is parked and should not enter the lifecycle yet
When they run `telec todo create parked-idea "<content>" --kind change --icebox`
Then the request carries kind="change" and icebox=True
And the route writes state + `input` artifact with the roadmap entry's status set to "icebox"
And the route emits the todo-created event with pickup_requested=false
And the lifecycle runner skips the iceboxed slug and spawns no session
And the todo waits in the icebox until `telec todo unfreeze parked-idea` returns it to active
```

#### UC-WTC18: Held create writes active held state and exposes it through todo state views

```
Given a live-human prepare orchestrator needs to own a new todo before the runner can claim it
When they run `telec todo create held-change "<content>" --kind change --hold --reason "live-human prepare owns this todo"`
Then the request carries kind="change", hold=True, and reason="live-human prepare owns this todo"
And the route writes the roadmap entry with status="active", the default state, and the `input` artifact
And the persisted state has hold=True and hold_audit.source="creation" with the stated reason
And `telec todo show held-change` exposes the held state, its hold_audit.source, and the stated reason
And `telec todo list` projects the same active row as held, reusing the existing hold projection that update-created holds use
```

#### UC-WTC19: Held create suppresses auto dispatch until release

```
Given a todo is created with `telec todo create held-change "<content>" --kind change --hold --reason "live-human prepare owns this todo"`
When the route emits the todo-created event
Then the payload carries pickup_requested=false
And the lifecycle router consumes the event without dispatching a session
And the lifecycle runner skips the active held todo as HELD
And after `telec todo update held-change --release` the active todo becomes eligible for its normal lane once other gates are satisfied
```

#### UC-WTC20: Hold and icebox are mutually exclusive at create time

```
Given a caller submits a create request carrying both hold=True and icebox=True
When the workflow service validates the request
Then the create is rejected before any roadmap row, state, `input` artifact, or todo-created event is written
And the diagnostic names hold and icebox as mutually exclusive
```

#### UC-WTC12: Group create attaches a child and upgrades the parent to a holder

```
Given an operator wants to create a child of an existing parent in one call, and parent-slug's lifecycle_phase has not yet reached "prepared"
When they run `telec todo create child-a "<content>" --kind change --group parent-slug`
Then the request carries kind="change" and group="parent-slug"
And the route writes "child-a"'s state + `input` artifact with a group reference to the parent row's durable id
And the same write transitions "parent-slug"'s row to status holder, removes its `todo_state`, voids any claim or hold on it, and preserves all of its artifacts and their version history as frozen evidence
And the route emits the todo-created event for "child-a" so its own lane proceeds under the normal dependency gate
And this applies because parent-slug's lifecycle_phase has not yet reached "prepared" — a parent at or past "prepared" is refused (see UC-WTC16)
```

#### UC-WTC15: Holder artifacts are frozen — a write to a holder is refused with a clean 409

```
Given "parent-slug" has status holder
When a caller attempts to write any non-`input` artifact to "parent-slug"
Then the workflow service refuses the write with a 409 conflict naming the slug as a holder
And the holder's retained frozen `input` artifact is left unchanged
And the caller is directed to write to the holder's children instead
```

#### UC-WTC16: Group create is refused once the parent has reached prepared or the work lane

```
Given "parent-slug"'s lifecycle_phase has reached "prepared" or a work-lane phase (build_started, review_approved, etc.)
When an operator runs `telec todo create child-a "<content>" --kind change --group parent-slug`
Then the filing is refused, naming "parent-slug" and its lifecycle_phase
And "parent-slug"'s `todo_state` and artifacts are left intact
And no roadmap row, state, or artifact is created for "child-a"
```

#### UC-WTC13: Project-root create targets an explicit project

```
Given an operator wants to create a todo against a project other than the invocation cwd
When they run `telec todo create remote-task "<content>" --kind change --project-root /path/to/other-project`
Then the CLI sends the create request with cwd resolved from the supplied project root
And the workflow service writes the todo into that project's workflow state, not the invocation cwd's
And the emitted todo-created event payload's project_path reflects the targeted project root
And the lifecycle runner acts against the targeted project
```

#### UC-WTC14: Removed create-time parking flags are rejected

```
Given a caller submits a create request carrying a retired parking field — `--release` or the hidden `--silent` (or the corresponding `release`/`silent` request body field)
When the workflow service validates the request body
Then the create is rejected at the request boundary (fail-closed) rather than silently accepted
And no roadmap row, state, `input` artifact, or todo-created event is written
And the `hold` field is accepted (it is the hidden specialist dispatch brake — see UC-WTC18)
```

```
Given a human or agent already has a complete implementation plan
When they run `telec todo create my-feature "<content>" --kind change --plan`
Then the request carries kind="change" and plan=true
And the route writes the content as the `implementation-plan` artifact (body prefixed "# my-feature — Implementation Plan")
And the route seeds the prepare lifecycle at plan-drafting so lifecycle_phase becomes "plan_drafting"
And the route emits the todo-created event with canonical kind="change" and pickup_requested=true
And the lifecycle router dispatches /sdlc/prepare, where the planner grounds the supplied plan, reflects affected doc snippets, and the plan is reviewed before prepared
And the outcome delivered to the filing session names the created todo "my-feature" and its kind
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

#### UC-WTC34: A creation request without a kind is refused

```gherkin
Given an operator or agent files a todo without choosing a kind
When the creation request reaches any creation door
Then no todo, state, artifact, or creation event is written
And the caller is told the kind is required and shown the four kinds: feature, change, bug, task
```

#### UC-WTC6: Task create enters task-plan drafting

```gherkin
Given a human or agent creates a task with substantive input
When they run `telec todo create call-supplier-api "<what to do>" --kind task`
Then workflow writes the roadmap row, Todo state, and `input` artifact atomically
And sets kind="task" and lifecycle_phase="task_plan_drafting"
And emits the todo-created event with kind="task", lifecycle_phase="task_plan_drafting", and project identity
And the lifecycle runner may dispatch `/sdlc/prepare-task`
And the task cannot dispatch `/sdlc/run-task` until a `task-plan` exists and the human authorization stamp is present
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
And the todo lands at lifecycle_phase="prepared" without dispatching `/sdlc/prepare-task`
And workflow records a `task_approved` stamp whose `approved_digest` equals the seeded `task-plan` digest
And the lifecycle runner dispatches `/sdlc/run-task` once the dependency or schedule gate passes, with no separate human authorization
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
Given a customer-support agent completes the pre-filing interrogation and files a bug via `telec bugs report`
When the workflow service handles the bug creation with kind="bug"
Then it writes state + todo entry + `input` artifact and enters the diagnose phase
And the workflow service emits the todo-created event with canonical kind="bug" and pickup_requested=true
And the lifecycle router consumes the event and dispatches /sdlc/prepare for the bug lane (diagnosis → plan → plan-review)
And the bug skips the demo phase per the kind=bug lifecycle gate
```

#### UC-WTC27: Bug report invocation interrogates before filing

```gherkin
Given an agent invokes `telec bugs report '<description>'` carrying only the report payload
When the command runs
Then it prints the pre-filing decisions to stderr: fix-directly-in-context (five-minute rule), duplication (todo list, in-flight bug lanes, suppressions), ordering behind in-flight work, and validity plus owning project
And the owning-project decision states that a symptom which stops once the observing project's own configuration matches a TeleClaude default is that project's to fix, and files nothing
And exits 0 without creating a todo — serving the interrogation is the successful outcome of that invocation
And only that output names how to complete the filing
And the surface verifies the decisions were faced, never that the answers are true — judging the answers stays with intelligence
```

#### UC-WTC28: Todo creation interrogates before creating

```gherkin
Given an agent is creating a todo through `telec todo create <slug> <content>`
When the agent invokes the command without the acknowledgment flag
Then the command presents the pre-creation decisions and creates no todo
And it names how to acknowledge those decisions
When the agent acknowledges them and requests lifecycle entry with declared pending documentation
But any declared pending document lacks a matching commit association, independent approval, or a current reviewed version
Then creation is refused before any todo state, artifact or dispatch is produced
And the refusal identifies the missing, unresolved or stale evidence and the commit or review action required
When the documentation evidence is independently approved and current and the agent submits a new acknowledged creation request
Then that new request passes the documentation evidence check and proceeds through the existing remaining creation checks
And work genuinely declaring no documentation delta keeps its existing creation route
And icebox filing keeps its parking route with the evidence check at lifecycle entry
```

#### UC-WTC8: Direct human filing records the human root alone

```gherkin
Given a human creates a todo from the TUI or a logged-in terminal, with no agent session
When the workflow service writes the roadmap row
Then `lineage` records the human root alone as `human:<email>`
And `entry_point` records the door used (`tui` or `cli`), stamped by the door itself
And `human_involved` is `true`, derived mechanically from the human door
And the emitted todo-created event payload carries the same creation record
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

#### UC-WTC22: Human-involved agent filing is resolved from observed presence

```gherkin
Given an agent files a todo from input a human shaped
And the session's latest authenticated human input falls within the code-owned recency window
When the agent passes a non-empty reason through `--human-involved` on that create or bug-report call
Then `human_involved` is recorded `true`
And the reason remains only in the invoking session's transcript
And the reason is absent from the todo, its artifacts, events, logs, output, and UI
And `lineage` still records the full chain while `entry_point` remains `agent`
And the record supplies no involvement value to preparation, work, review, integration, or any later filing
```

#### UC-WTC31: Agent filing refuses only a malformed involvement declaration

```gherkin
Given an agent files a todo or bug with a missing or blank human-involvement reason
When the creation surface validates the invocation
Then it refuses the call before creating the todo
And it emits no supplied reason
And the diagnostic directs the agent to rerun without the declaration when the filing is not human-involved
```

#### UC-WTC33: A stale declaration records false and the filing proceeds

```gherkin
Given an agent files a todo or bug with a non-empty human-involvement reason
And the session's latest authenticated human input is absent or older than the code-owned recency window
When the creation surface resolves the record
Then `human_involved` is recorded `false`
And the todo is created exactly as it would have been without the declaration
And a structured record reports the discard, the acting session's full identifier, and the observed age of the last human input
And that record carries no part of the supplied reason
```

#### UC-WTC32: Todo involvement never propagates

```gherkin
Given a todo creation recorded human_involved=true
When any later lifecycle act or another filing occurs without its own admissible declaration
Then that later act records its own default involvement value
And the todo's creation record supplies no authorization, approval, or inherited involvement
```

#### UC-WTC23: A lineage-less create fails loudly

```gherkin
Given a create call whose caller identity resolves to no lineage root — neither a human (a human principal, or a verified human email) nor the platform's principal
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

#### UC-WTC26: A system-rooted session's filing is the legitimate no-human lineage

```gherkin
Given a caller acting as the platform's principal — the daemon itself, a standing session (the integrator, the project coordinator, or a scheduled job's session), or a session one started — files a todo or a bug with no human at its chain root
When the workflow service writes the roadmap row
Then `lineage` records `system:daemon` as its root, and the filing session as its acting session when the caller is a session
And `human_involved` is `false`
And any other session filing without a resolvable root is rejected per UC-WTC23
```

#### UC-WTC24: Group create succeeds against a prepare-lane parent carrying prepared artifacts

```gherkin
Given "parent-slug" is mid-plan-review, carrying `prd`, `architecture`, `implementation-plan`, and `plan-review-findings` artifacts with version history
When an operator runs `telec todo create child-a "<content>" --kind change --group parent-slug`
Then the create succeeds and "child-a" is attached with a group reference to the parent row's durable id
And "parent-slug"'s row transitions to status holder and its `todo_state` is removed
And every artifact "parent-slug" carried survives unchanged, with its full version history, as frozen evidence
And a subsequent write or remove against "parent-slug" is refused with a 409, so the preserved evidence is read-only
```

#### UC-WTC35: A filing made while other sessions commit reports its own outcome

```gherkin
Given an agent files acknowledged work through `telec todo create` or `telec bugs report`
And another session is committing or publishing to main at the same time
When the filing's request passes its request checks
Then the command returns the filing's receipt within its response deadline, without waiting for that git work
And the filing waits for that git work to finish, then checks its documentation evidence as it stands once that work is done
And the agent's session is delivered the todo created when that evidence holds
And otherwise the filing refused for the missing, unresolved or stale evidence, with no todo state, artifact or dispatch produced
And a filing whose todo was created is never reported to the agent as a timeout or a refusal
```

#### UC-WTC36: Filings of one project complete in the order they were accepted

```gherkin
Given an agent files "parent-slug" and, before that filing has completed, files "child-a" with `--after parent-slug`
When both requests pass their request checks and return receipts
Then the filing of "child-a" starts only after the filing of "parent-slug" has ended
And when "parent-slug" was created, "child-a" is created with its dependency on "parent-slug" recorded
And when "parent-slug" was refused, "child-a" is refused for its unknown dependency, and each outcome is delivered to the agent's session
And a filing in another project neither waits for these filings nor is waited for by them
```

### Dependency gate at create-time

Create-time dispatch is dependency-gated by the lane selected from the creation event. The executable scenarios are `UC-WTC2` and `UC-WTC3`.

### Use cases

#### UC-WTC1: Create help exposes canonical kind choices

```gherkin
Given an operator needs to create a todo
When they run `telec todo create --help`
Then the usage line shows `--kind` as required with values `feature|change|bug|task`
And the help does not advertise retired kind values
And the usage line and the Options table do not advertise the hidden `--hold` flag, which the Notes are free to explain
```

#### UC-WTC2: Dep-blocked create event is consumed without prepare dispatch

```gherkin
Given a human runs `telec todo create child "<content>" --kind change --after parent` while "parent" has not yet reached PREPARED
When the workflow service creates "child" and emits the todo-created event with pickup_requested=true
And the lifecycle router consumes the event
Then the router consults the dependency graph and finds "child"'s prepare gate unsatisfied (parent not PREPARED)
And the router treats the dep-blocked child as silent — it does not dispatch /sdlc/prepare for "child"
And the router logs "skipped: dependency-blocked" with the unsatisfied parent slug
And "child" waits until "parent" reaches PREPARED, at which point auto-continue dispatches it (see @spec/feature/workflow/prepare-state-machine)
```

#### UC-WTC3: Deps-satisfied create event dispatches prepare

```gherkin
Given a human runs `telec todo create child "<content>" --kind change --after parent` while "parent" is already PREPARED
When the lifecycle router consumes the todo-created event for "child"
Then the router finds "child"'s prepare gate satisfied
And the router dispatches /sdlc/prepare for "child" as usual
```

#### UC-WTC29: A held create carries the reason it is parked

```gherkin
Given a live-human prepare orchestrator needs to own a new todo before the runner can claim it
When they run `telec todo create held-change "<content>" --kind change --hold --reason '<why this waits, or the gate or owner it waits on>'`
Then the persisted state has hold=True and hold_audit.source="creation" with the stated reason, the time, and the caller session id
And `telec todo show held-change` exposes that source and reason together
And a `--hold` create whose reason is missing or blank is refused before any roadmap row, state, `input` artifact, or todo-created event is written
And a `--reason` supplied without `--hold` is refused before any write rather than ignored
And the reason input is hidden from the structured flag surfaces exactly as `--hold` is
```

#### UC-WTC30: Creation refuses a slug that violates the kebab-case invariant

```gherkin
Given an agent runs `telec todo create My_Slug "<content>" --kind change`
When the workflow service validates the creation request
Then the create is refused before any roadmap row, state, `input` artifact, or todo-created event is written
And the diagnostic names the slug format the invariant requires
And a slug carrying a path separator or a relative-path segment is refused the same way
And each `--after` dependency slug and the `--group` parent slug are held to that same format invariant
```

### Cross-context references

- `operations` — async, receipt-backed operations (e.g., `telec todo remove`) are surfaced through the operations subsystem; a filing is one of them, as Filing under a receipt states.

- `integration` — the lifecycle router consumer consumes the todo-created event and dispatches lane-appropriate orchestrators (`/sdlc/prepare`, `/sdlc/work`).

- `agent_runtime` — the creative state machine driven by `telec todo design` spawns and supervises creative sessions through `agent_runtime`.

## Known caveats

- `<content>` is a required positional on `telec todo create`. Empty or whitespace-only content is rejected by the CLI before any request; the workflow service also rejects it as a second line of defense.

- `--kind` is **required** on `telec todo create`. The valid kinds are `feature`, `change`, `bug`, and `task`, and a request without one is refused before anything is written. A bare `task` is created silent and enters `task_plan_drafting`, where `/sdlc/prepare-task` authors its `task-plan`. Use `--plan` with `--kind change` when the content is a complete implementation plan and should seed the implementation plan into plan-drafting before plan review, or with `--kind task` when the content is a complete `task-plan`: the task is born `prepared` and pre-authorized (the `task_approved` stamp is written at creation, digest-bound to the seeded `task-plan`), so the runner routes it straight to `/sdlc/run-task` once its dependency or `schedule` gate passes.

- A created todo enters its kind's lifecycle; nothing holds it back at creation by default. Two flags suppress create-time dispatch (`pickup_requested=false`): `--icebox` parks it in the icebox (`status="icebox"`), and `--hold` leaves it **active** but sets the durable dispatch brake (`hold=True`, `hold_audit.source="creation"`). The lifecycle runner skips both — iceboxed entries by status, held entries by the hold brake — until the icebox is unfrozen or the hold is released. The two are mutually exclusive. The route always emits the todo-created event after a successful create.

- `--group <parent-slug>` is the create-time path to a grouped child. It records the child's group reference to the parent row's durable id inside the create transaction. The first grouped child transitions the parent's row to status `holder` in the same transaction — removing its `todo_state` and voiding any claim or hold — while preserving all of its artifacts and their version history as frozen evidence, so a parent still in the prepare lane can be grouped without shredding prepared work (see UC-WTC24). A parent whose lifecycle_phase has reached `prepared` or the work lane is refused instead (see UC-WTC16). `--release` is not accepted on create; `--hold` is the hidden create-time dispatch brake (see UC-WTC18). Grouping also moves the parent's pending documentation ownership to the first grouped child: every in-body marker, companion filename, and `delivered_by` membership naming the parent is rewritten to that child and committed as part of the same transition.

- The `bugs report` helper wraps the same creation path with `kind=bug`. The prior CLI-side bug-emit helper has been removed; the workflow service is now the single emission point for bug creation as well.
- The lifecycle router selects the lane from the event payload's `kind`, `lifecycle_phase`, and `pickup_requested`, then consults todo state only for dependency gating before auto-dispatch. `telec todo create` emits canonical `feature`, `change`, `bug`, or `task` kinds.

- **Dependency gate at create-time:** routing by `kind`/`lifecycle_phase`/`pickup_requested` selects the _lane_, but before auto-dispatching the router consults the dependency graph for the slug. A child with unsatisfied `after` dependencies for its lane (prepare lane → parents must be `PREPARED`; work lane → parents must be `delivered`, per `@spec/feature/workflow/dependency-graph`) is treated as silent: the event is still consumed but no orchestrator is dispatched. Only deps-satisfied todos auto-dispatch. This closes the create-time over-dispatch where `create parent; create child --after parent` spawned both orchestrators in parallel.

- `telec todo design` is the creative state machine entrypoint. It is NOT a Todo-creation entrypoint on its own — it orchestrates creative phases (design-spec, art, visuals) against an existing slug or auto-selects from the todo list.
- The CLI's `--after` parser splits on commas after trimming; empty entries are dropped. Dependency-existence validation happens when the entry is inserted, not in the CLI.
- The `--plan` path writes content prefixed with `# <slug> — Implementation Plan\n\n` for `--kind change` and `# <slug> — Task Plan\n\n` for `--kind task`; the default path writes content prefixed with `# <slug> — Input\n\n`. Callers should not pre-add those headers in the supplied content.

- The todo-created event payload's creation record (`lineage`, `entry_point`, `human_involved`, `context`) is populated from the roadmap row's persisted values. `todo_id` and `project_id` may still not be populated by every emitter; downstream consumers fill those via serde defaults.
- Answering "who created this todo" means reading the creation record — `entry_point`, `lineage`, `human_involved`, `context` — never inferring from account identity. The lineage root is the authority the work ran under, not the author of the work.

## See Also

- docs/local/adr/0104-every-todo-is-created-with-its-kind.md — why kind is required at creation.
- docs/local/adr/0138-a-filing-completes-after-its-request-under-a-receipt.md — why a filing returns a receipt and completes in its project's acceptance order.
