---
id: project/spec/domain/workflow
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by: [v2-workflow-cutover]
description: Workflow bounded context — todos, roadmap entries, preparation artifacts, lifecycle state machines. The system that organizes what gets built.
---

# Workflow Domain Spec — Spec

## Required reads

- @docs/global/software-development/principle/domain-driven-design.md
- @docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md
- @docs/project/spec/domain/event-catalog.md

## What it is

The `workflow` bounded context owns the platform's todos, roadmap, and the state machines that drive a todo from idea to delivered. It owns the preparation artifacts (PRD, architecture, test specs, implementation plan, etc.), the stage and phase progressions per todo, the dependency graph between todos, and the bookkeeping that makes the work visible.

This context does NOT own: the live agent sessions doing the work (`agent_runtime`), the transcript history of those sessions (`session_ledger`), the doc snippet content (`knowledge`), or the integration that delivers outbound notifications (`integration`). Workflow is local-first and authoritative for the per-project todo store; it operates without daemon dependency for its core operations.

## Canonical fields

### Ubiquitous language

**Todo**
:  A unit of work flowing through the lifecycle. Has a slug, a kind, a stage, current phase within stage, a set of artifacts. The atomic deliverable unit of workflow.

**Slug**
:  A kebab-case unique identifier for a todo. Stable across the todo's lifetime. The primary key.

**Kind**
:  Categorical label for the type of work: `feature`, `bug`, `refactor`, `migration`, `prepped`. Determines which lifecycle gates apply (e.g., `bug` skips the demo phase in finalize; `prepped` skips prepare).

**Stage** (per glossary)
:  Top-level lifecycle band: `draft`, `prepare`, `work`, `integrate`, `delivered`. Each stage is a coherent body of work with its own state machine inside.

**Phase** (per glossary)
:  Sub-state within a stage. Examples for `prepare` stage: `intake`, `prd_drafting`, `prd_human_approval`, `architecture_drafting`, `architecture_review`, `test_specs_drafting`, `test_specs_review`, `plan_drafting`, `plan_review`, `drift_analysis`, `prepared`.

**Artifact** (workflow artifact — per glossary)
:  A document produced during a todo's lifecycle. Canonical kinds: `input`, `prd`, `architecture`, `test-specs`, `implementation-plan`, `bug`, `quality-checklist`, `design-spec`, `deferrals`, `requirements-review-findings`, `architecture-review-findings`, `spec-review-findings`, `plan-review-findings`, `review-findings`. Stored as TEXT in `workflow.artifacts`.

**Roadmap**
:  The ordered list of todos with their dependency edges, groupings, and statuses. The public face of "what's being worked on and what's next."

**Roadmap entry**
:  One row in the roadmap representing one todo. Carries: slug, status (`pending` | `ready` | `in_progress` | `delivered` | `icebox`), `after` (dependency slugs), `before` (insertion anchor), optional `group` and `description`.

**Dependency**
:  An `after` relationship between roadmap entries. Todo A is `after: [B, C]` means A cannot start until B and C are `delivered`.

**Icebox**
:  Frozen-but-recoverable state for roadmap entries that aren't being actively pursued. Lives at `todos/_icebox/`. Unfreeze restores to the active roadmap.

**State machine**
:  The engine that advances a todo's phase based on artifact production, review verdicts, and orchestrator decisions. Per-stage: prepare state machine, work state machine, integrate state machine.

**Verdict**
:  A reviewer's output on a workflow artifact: `approve`, `needs_work`, `needs_decision`. Drives state machine transitions.

**Operation**
:  A long-running task tied to a todo (e.g., a worker session doing build). Tracked as `agent_runtime.operations` from workflow's perspective via the `operation.completed` event.

**Delivery commit**
:  The git commit SHA on `main` that materialized the todo's outcome. Non-empty when stage is `delivered`. The audit trail anchor.

### Aggregates

#### Todo (aggregate)

- **Root:** `Todo`
- **Contains:** the Slug as identifier; current StageState (which stage, which phase, in_progress vs awaiting); the Artifact collection (each artifact has version history); dependency edges (`after` slugs); kind; optional grouping; optional description.
- **Invariants:**
  - A todo has exactly one current `(stage, phase)` at any moment.
  - Stage progression is strictly forward: `draft → prepare → work → integrate → delivered`. No backwards transitions; recovery from failure happens within the current stage's machine.
  - An artifact's version history is append-only; old versions are referenced by digest.
  - A todo's `kind` is fixed at creation; changing kind requires deletion + recreation.
  - A todo cannot reach `delivered` stage without a non-empty `delivery_commit` and a successful integrate-state-machine terminal state.
  - Dependency cycles are forbidden — the dependency graph MUST be a DAG.
  - A todo's slug is immutable across its lifetime.
- **Identifier:** slug.
- **Lifecycle:** Created via `telec todo create` (empty draft skeleton), `telec todo dump` (with input attached), or `telec todo split` (child of a container). Advances through stages via the per-stage state machine. Reaches `delivered` via integration. Frozen aggregates move to icebox.

#### Roadmap (aggregate)

- **Root:** `Roadmap` (per-project; one roadmap per `.teleclaude/todos.db`)
- **Contains:** ordered list of `RoadmapEntry` values, each referencing a Todo by slug; the dependency graph; optional group labels.
- **Invariants:**
  - Every roadmap entry references exactly one todo (1:1).
  - The dependency graph (`after` edges across all entries) is a DAG.
  - Ordering within the roadmap is explicit and operator-controlled (via `move`, `add --before`, `add --after`); the system does not auto-reorder.
  - Icebox entries do NOT participate in the active dependency graph; unfreezing restores them.
  - Delivered entries remain in the roadmap (visible via `--include-delivered`) for history.
- **Identifier:** the per-project roadmap is unique per project; no separate identifier.
- **Lifecycle:** Created when the project is initialized. Mutated by `telec roadmap add/remove/move/deps/freeze/unfreeze/deliver`. Persists for the project's lifetime.

#### Artifact (aggregate, lives inside Todo)

- **Root:** `Artifact`
- **Contains:** kind (one of the canonical artifact kinds); content (TEXT); version history (digest + timestamp per version); current version pointer.
- **Invariants:**
  - Artifact content is append-only at the version level; replacing content creates a new version, never mutates an existing one.
  - Each artifact kind is unique per todo (one `prd` per todo, one `implementation-plan` per todo, etc.).
  - Removing an artifact (`telec todo artifacts remove`) deletes the artifact + its full version history.
  - The current version pointer is the most-recently-written version.
- **Identifier:** `(todo_slug, artifact_kind)`.
- **Lifecycle:** Created by `telec todo artifacts write` or as a side effect of state-machine transitions. Versioned on every write. Removed by explicit `telec todo artifacts remove`.

### Domain events emitted

#### `workflow.todo.created`

- **Producer:** `workflow`
- **Emitted when:** a new todo is added to the roadmap (via `create`, `dump`, `split`, `bugs report`, `bugs create`).
- **Payload:** `slug`, `kind`, `stage` (always `draft` initially), `created_at`, `created_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers:** `integration` (subscription notifications for "todo created"), audit log consumers.
- **Idempotency key:** `slug`.
- **Posture:** `commit-then-emit`.

#### `workflow.todo.updated`

- **Producer:** `workflow`
- **Emitted when:** any mutation to a todo's metadata or artifacts that does NOT change its phase (artifact write, description change, dependency edit).
- **Payload:** `slug`, `updated_at`, `change_summary` (string), `updated_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (live roadmap view refresh), `telec-tui` (cache invalidation).
- **Idempotency key:** `(slug, updated_at)` with millisecond precision.
- **Posture:** `commit-then-emit`.

#### `workflow.todo.phase_advanced`

- **Producer:** `workflow`
- **Emitted when:** the state machine advances a todo's phase (e.g., `prd_drafting` → `prd_human_approval`, `prepared` → `work:building`).
- **Payload:** `slug`, `from_stage`, `from_phase`, `to_stage`, `to_phase`, `advanced_at`, `triggered_by_principal`, `verdict` (when applicable).
- **Visibility:** CLUSTER
- **Known consumers:** `integration` (notification dispatch for phase milestones), `frontend` (UI refresh), `telec-tui` (cache invalidation).
- **Idempotency key:** `(slug, advanced_at)`.
- **Posture:** `commit-then-emit`.

#### `workflow.todo.delivered`

- **Producer:** `workflow`
- **Emitted when:** the integrate state machine reaches its terminal state and stamps `delivery_commit` on the todo.
- **Payload:** `slug`, `delivery_commit`, `delivered_at`, `delivered_by_principal`, `branch_name`.
- **Visibility:** CLUSTER
- **Known consumers:** `integration` (delivery announcement), `agent_artifacts` (potentially: re-sync if delivery touched artifact sources), `frontend` (status update).
- **Idempotency key:** `(slug, delivery_commit)`.
- **Posture:** `commit-then-emit`.

#### `workflow.roadmap.entry_moved`

- **Producer:** `workflow`
- **Emitted when:** an operator changes the order of entries (via `telec roadmap move`), changes a dependency edge (`deps`), or freezes/unfreezes an entry.
- **Payload:** `slug`, `change_type` (`reordered` | `dependency_changed` | `frozen` | `unfrozen` | `delivered`), `details`, `moved_at`, `moved_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (roadmap view refresh), `telec-tui` (cache invalidation).
- **Idempotency key:** `(slug, change_type, moved_at)`.
- **Posture:** `commit-then-emit`.

### Domain events consumed

#### `agent_runtime.operation.completed`

- **Producer:** `agent_runtime`
- **Reaction:** when an operation tied to a workflow phase completes (e.g., a build session reports `FINALIZE_READY`), workflow advances the relevant todo's phase per the state machine.
- **Failure handling:** if the state machine rejects the advance (e.g., precondition violated), the rejection is logged; the operation is treated as a no-op from workflow's side; the orchestrator (which dispatched the operation) decides whether to retry.

#### `config.effective.updated`

- **Producer:** `config`
- **Reaction:** invalidate cached effective configuration values used by workflow handlers (operator role mappings, default dispatch agents, etc.).
- **Failure handling:** stale configuration is tolerated for one request; the next read after the event flushes the cache.

### Use cases

#### UC-WFL-1: Create a draft todo skeleton

```
Given an operator (or agent) wants to scaffold work
When they run `telec todo create my-feature --kind feature --after upstream-slug`
Then workflow validates the slug is unique and kebab-case
And validates `upstream-slug` exists in the roadmap
And creates a Todo aggregate at (stage=draft, phase=draft, state=in_progress)
And adds a RoadmapEntry with after=[upstream-slug], status=pending
And emits workflow.todo.created
```

#### UC-WFL-2: Dump a fully-formed input as a new todo

```
Given a human or agent has a substantive idea written up
When they run `telec todo dump my-feature "<content>"`
Then workflow creates the Todo as above
And creates the input Artifact with content
And emits workflow.todo.created
And (unless --draft) triggers downstream pickup signals
```

#### UC-WFL-3: Advance through the prepare state machine

```
Given a todo is at (stage=prepare, phase=prd_drafting)
And a prepare worker authored the prd Artifact
When the prepare-orchestrator calls into the workflow state machine
Then workflow validates the prd Artifact exists and is non-empty
And advances to (phase=prd_human_approval, state=awaiting_human)
And emits workflow.todo.phase_advanced
And does NOT auto-advance without an explicit human approval signal
```

#### UC-WFL-4: Authored artifact is persisted with version history

```
Given a worker writes an Artifact via `telec todo artifacts write <slug> <kind> <content>`
When the write executes
Then workflow stores the content as a new version with digest
And updates the artifact's current-version pointer
And emits workflow.todo.updated
And the previous version remains addressable by digest for diff
```

#### UC-WFL-5: Stamp human approval and advance

```
Given a todo is awaiting human approval at a gate phase (prd, architecture, test-specs, plan)
When an operator runs `telec todo stamp <slug> --<artifact>-approved`
Then workflow records the approval on the state
And the state machine advances to the next phase
And emits workflow.todo.phase_advanced with verdict=approve
```

#### UC-WFL-6: Roadmap entry moves to icebox

```
Given an operator decides a roadmap entry is not currently being pursued
When they run `telec roadmap freeze <slug>`
Then workflow moves the entry's filesystem to todos/_icebox/<slug>/
And marks the roadmap entry status=icebox
And the entry no longer participates in dependency resolution for active entries
And emits workflow.roadmap.entry_moved with change_type=frozen
And `telec roadmap list` no longer shows it by default
```

#### UC-WFL-7: Delivery stamps the integration outcome

```
Given a todo has completed the integrate state machine successfully
When the integrator stamps the delivery commit (workflow.deliver(slug, commit_sha))
Then workflow sets the todo's stage=delivered, delivery_commit=<sha>
And emits workflow.todo.delivered
And the roadmap entry status becomes delivered
And the todo's worktree (if any) is eligible for cleanup
```

#### UC-WFL-8: Reconcile within a stage after evidence change

```
Given a todo's artifacts or state evidence has changed without going through normal advance
And the operator runs `telec todo reconcile <slug> --stage prepare`
When the reconciler runs
Then workflow re-evaluates the prepare state machine against current evidence
And aligns lifecycle_phase to match (without skipping forward beyond what evidence supports)
And emits workflow.todo.phase_advanced if the alignment changed phase
```

#### UC-WFL-9: Dependency violation blocks dispatch

```
Given a todo X has after=[Y]
And Y is not in delivered state
When an orchestrator tries to dispatch work on X
Then the state machine refuses the transition
And the orchestrator is told which dependencies are unmet
```

### Context map position

- **Customer-Supplier downstream of `identity`** — every workflow operation that mutates state requires a resolved Principal for authorization.
- **Customer-Supplier downstream of `knowledge`** — the prepare-orchestrator and build workers receive context selections from knowledge to ground their session.
- **Customer-Supplier downstream of `agent_runtime`** — workflow subscribes to `agent_runtime.operation.completed` to advance phases.
- **Customer-Supplier upstream to `integration`** — workflow's phase-advance and delivery events drive notification dispatch.
- **Reads from `config`** — operator role mappings, default dispatch agents, etc.
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/core/todos_db/` (SQLite per project) is the authoritative store today. The v2 ACL at `crates/workflow/src/v1_compat.rs` (planned) translates v1 row shape into v2 aggregates. The v1 cutover (`v2-workflow-cutover`) requires migrating EVERY v1 caller together (CLI, API, TUI, orchestrators, internal callers) — see `reconstruction-order.md` cutover safety section.

## Allowed values

- `kind`: `feature`, `bug`, `refactor`, `migration`, `prepped`.
- `stage`: `draft`, `prepare`, `work`, `integrate`, `delivered`.
- `prepare phases`: `intake`, `prd_drafting`, `prd_human_approval`, `architecture_drafting`, `architecture_review`, `test_specs_drafting`, `test_specs_review`, `plan_drafting`, `plan_review`, `drift_analysis`, `prepared`.
- `work phases`: `pending`, `building`, `review_pending`, `review_complete`, `fixing`, `finalize_pending`, `finalize_ready`.
- `integrate phases`: per `integration-state-machine` design doc (squash, conflict-resolve, lint, test, push, deliver).
- `roadmap status`: `pending`, `ready`, `in_progress`, `delivered`, `icebox`.
- `artifact kind`: `input`, `prd`, `architecture`, `test-specs`, `implementation-plan`, `bug`, `quality-checklist`, `design-spec`, `deferrals`, `requirements-review-findings`, `architecture-review-findings`, `spec-review-findings`, `plan-review-findings`, `review-findings`.
- `verdict`: `approve`, `needs_work`, `needs_decision`.

## Known caveats

- Workflow is **local-first**: every operation works against the per-project Postgres schema (or SQLite in v1) without daemon dependency. The `telec` binary embeds workflow directly. The daemon is a CONSUMER of workflow events (for orchestration), not a host.
- The state machine is a Rust crate (`crates/state_machine`) embedded by workflow. State machine state lives in `workflow.state_transitions`; transitions are persisted as the source of truth for phase advances.
- Per-project isolation: each project has its own `.teleclaude/todos.db` (v1 SQLite) or its own Postgres schema (v2, possibly `<project>_workflow`). No cross-project queries.
- `prepped` kind todos skip the prepare lifecycle entirely. Used when a human or agent has authored a complete implementation plan and wants to jump to build. Per the `--prepped` flag's policy: HUMAN-IN-THE-LOOP REQUIRED.
- `bug` kind todos skip the demo phase during finalize and require the orchestrator to manually mark `build complete` before advancing (per agent memory gotcha).
- The orchestrator (`teleclaude/core/next_machine/` in v1) is a CONSUMER of workflow, not part of it. The orchestrator dispatches sessions, reads workflow state, calls workflow mutations. Workflow itself has no opinion about WHO advances todos — it enforces invariants on transitions and exposes events.
- Reviewer findings artifacts are workflow artifacts (per the canonical list) even though they're produced by review sessions. The state machine treats `review-findings` artifact presence + verdict as the trigger for advance.
