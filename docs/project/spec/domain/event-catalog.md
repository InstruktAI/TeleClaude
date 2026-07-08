---
description: 'Every domain event the platform emits — producer context, named consumers, payload field set in domain terms. The contract that defines cross-context coordination.'
visibility: 'public'
---

# Domain Event Catalog — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @docs/project/design/architecture-v2/event-bus-transports.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The exhaustive catalog of domain events emitted by the platform's bounded contexts. Each event is named in the producing context's ubiquitous language, carries a payload of domain-meaningful fields, and lists its known consumers.

This catalog is the contract that defines cross-context coordination: when two services interact via events (per the context-map relationships), this document is where the wire shape is fixed. Code that emits events must match the catalog; code that consumes events depends on the catalog. The catalog evolves through PRs that touch both this file and the producing context's domain spec.

Skeleton on first commit: structure + lifecycle/spine context events. Per-context expansion happens as each domain spec is authored.

## Canonical fields

### Naming convention

Every event name follows: `<context>.<noun>.<past-tense-verb>` or `<context>.<past-tense-verb>` when no sub-noun is meaningful.

- `<context>` — one of the platform services (`workflow`, `identity`, `config`, `context`, `agent_runtime`, `session_mirrors`, `integration`, `memory`, `reconciliation`). v2 fold: `knowledge` + `agent_artifacts` collapsed into `context`; `memory` added.

- `<noun>` — the entity or aggregate the event is about (optional; omitted when the context only has one primary subject).
- `<past-tense-verb>` — what happened (`created`, `updated`, `deleted`, `started`, `ended`, `received`, `delivered`, `phase_advanced`, etc.).

Examples: `workflow.todo.created`, `agent_runtime.session.started`, `integration.outbox.delivered`, `memory.observation.saved`.

### Per-event description format

Each event below carries:

- **Name** — `<context>.<noun>.<verb>`
- **Producer** — the context that emits the event
- **Emitted when** — the domain condition that triggers emission
- **Payload** — the data carried, in domain field names
- **Known consumers** — contexts (and external systems) that subscribe and act
- **Visibility** — per `event-bus-transports.md` posture: `LOCAL` (single-host Redis scope — events confined to this computer), `CLUSTER` (single-owner mesh Redis scope — cross-host within one user's fleet), `PUBLIC` (federation hub Redis scope — cross-mesh, rare). See the **Allowed values** section for the authoritative definition.
- **Idempotency key** — the field tuple that makes two emissions "the same event" for consumer dedup
- **Emit posture** — `commit-then-emit` (loud-fail) | `outbox` (atomic with caller commit) | `inbox` (durable capture then publish)

### Events

> **Status:** skeleton on first commit. Per-context specs append their events to the relevant section as they're authored. Order within a section is alphabetical by event name.

#### identity

| Event                        | Producer | Visibility | Posture          |
| ---------------------------- | -------- | ---------- | ---------------- |
| `identity.principal.created` | identity | CLUSTER    | commit-then-emit |
| `identity.token.issued`      | identity | CLUSTER    | commit-then-emit |
| `identity.token.revoked`     | identity | CLUSTER    | commit-then-emit |

**Detailed entries:** to be expanded by `project/spec/domain/identity` authoring.

#### config

| Event                      | Producer | Visibility | Posture          |
| -------------------------- | -------- | ---------- | ---------------- |
| `config.effective.updated` | config   | CLUSTER    | commit-then-emit |

**Detailed entries:** to be expanded by `project/spec/domain/config` authoring.

#### jobs

| Event               | Producer    | Visibility | Posture |
| ------------------- | ----------- | ---------- | ------- |
| `job.run.succeeded` | cron-runner | CLUSTER    | outbox  |
| `job.run.failed`    | cron-runner | CLUSTER    | outbox  |
| `job.run.stalled`   | cron-runner | CLUSTER    | outbox  |

The cron runner emits one event when a job run closes or is stalled. `job.run.succeeded`
is informational and silent; `job.run.failed` and `job.run.stalled` are actionable and
notify a human through the notification cartridge.

Under the `outbox` posture, each outcome is enqueued into the runner's owned run state
atomically with the run close/stall write. A per-tick sweep drains the queue and publishes
each outcome, removing an entry only after a confirmed publish; an unconfirmed publish stays
queued for the next sweep. The idempotency key makes delivery exactly-once across retries and
intervening ticks.

- **Emitted when** — a run closes with a real outcome (`succeeded`/`failed`), or an open
  run exceeds its expected window with no reported outcome (`stalled`).
- **Payload** — `job_name`, `status`, `message`, and `items_processed` for a closed run.
- **Known consumers** — the notification cartridge (projects actionable outcomes to admins).
- **Idempotency key** — `job_name` + `run_started_at`.

#### workflow

| Event                          | Producer | Visibility | Posture          |
| ------------------------------ | -------- | ---------- | ---------------- |
| `workflow.todo.created`        | workflow | CLUSTER    | commit-then-emit |
| `workflow.todo.updated`        | workflow | CLUSTER    | commit-then-emit |
| `workflow.todo.phase_advanced` | workflow | CLUSTER    | commit-then-emit |
| `workflow.todo.delivered`      | workflow | CLUSTER    | commit-then-emit |
| `workflow.roadmap.entry_moved` | workflow | CLUSTER    | commit-then-emit |
| `workflow.todo.renamed`        | workflow | CLUSTER    | commit-then-emit |

**Detailed entries:** to be expanded by `project/spec/domain/workflow` authoring.

`workflow.todo.renamed` carries `old_slug` + `new_slug` so slug-keyed
consumers (`frontend`, `telec-tui`, `integration`) can re-key rather than
orphan cache entries — see `project/spec/domain/workflow` for the full entry.
Pending delivery of `telec-todo-rename` (carried via `delivered_by`).

`workflow.todo.created` carries an extended payload — `creation_mode`
(`pickup` | `silent`) and `pickup_requested` (boolean) — added by
`v2-workflow-cli-refinement-commands`. The event is always emitted on
successful creation; pickup suppression for bulk-queueing flows is encoded in
the payload, not by hiding the state-change event. Autonomous pickup
consumers (prepare / work dispatch routers) dispatch only when
`pickup_requested = true`; cache, bridge-refresh, and audit consumers
process every creation event regardless of mode. See
`project/spec/domain/workflow` for the full entry.

`workflow.todo.created` also carries `created_by_agent` — the reporting agent's
session (`session:<session_id>`) — captured additively alongside
`created_by_principal` so an agent-filed todo is traceable to its reporting
agent even with no human at the chain root. Strict-additive; absent for a direct
human-terminal filing. See `project/spec/domain/workflow` for the full entry.

Autonomous pickup is driven by the workflow lifecycle runner. The canonical target wake-up vocabulary is
`workflow.todo.created`, `workflow.todo.updated`,
`workflow.todo.phase_advanced`, `workflow.todo.delivered`,
`workflow.roadmap.entry_moved`, `config.effective.updated`, and
`agent_runtime.session.ended`. A wake-up is usable only when it carries or can
resolve exactly one project identity (`project_id` in the target contract,
`project_path` in the v1 bridge); project-ambiguous events are skipped
fail-closed for runner dispatch.

The v1 Python delivery is grounded in the existing v1 event seams, not in an
assumption that every v2 event already fires:

| Target wake-up                                           | v1 status / required runner-dispatch wiring                                                                                                                                                                                                                                                                                                                    |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workflow.todo.created`                                  | Already emitted by the v1 todo API with `project_path`; the current lifecycle router consumes it.                                                                                                                                                                                                                                                              |
| `workflow.todo.phase_advanced`                           | Must be wired from the existing TodosDb/daemon phase-transition seam. Today that seam emits only `domain.software-development.planning.todo_finalize_ready` when the new phase is `finalize_ready`; this delivery generalizes the seam for eligibility-changing prepare/work phase transitions while preserving the existing finalize-ready integration event. |
| `workflow.todo.delivered`                                | Must be emitted or bridged from the v1 delivery stamp path; no v1 emit site is assumed.                                                                                                                                                                                                                                                                        |
| `workflow.todo.updated` / `workflow.roadmap.entry_moved` | Must be emitted or bridged from v1 mutation paths that change hold, dependency edges, icebox/unfreeze, or task authorization. Rust v2 emissions alone are insufficient while v1 remains authoritative.                                                                                                                                                         |
| `config.effective.updated`                               | Must be wired from the v1 config watcher/effective-config reload seam, or the runner must receive an equivalent in-process wake-up carrying the same scope semantics.                                                                                                                                                                                          |
| `agent_runtime.session.ended`                            | Must be bridged from v1 `SESSION_CLOSED` as a runner wake-up. The payload is not extended with close-intent metadata; the runner correlates the closed session to its todo (via `active_runner`) and resolves the project through the same identity path as other wake-ups.                                                                                    |
| `scheduler.tick.minute`                                  | Pending `task-lane`; v1 must add the in-daemon minute clock emitter and lifecycle-router admission for this wake-up before workflow can subscribe to it for schedule-gated tasks.                                                                                                                                                                              |

`creation_mode` / `pickup_requested` are migration-only fields after this
delivery. The durable target control is `workflow.Todo.hold` plus effective
autostart policy. Legacy operator-requested silent creation is translated to
`hold=true` at the workflow boundary; the v1 task `force_silent` default is
translated to `hold=false` plus task autostart disabled. Event consumers do not
treat silent wording as a separate dispatch state.

#### context

NO events emitted. `context` is filesystem-driven. Consumers re-read source/index on demand. `telec context sync` is the implicit "context changed" signal; downstream tools can subscribe to git or file watchers if reactive behavior is ever needed (none currently is).

**Detailed entries:** see `project/spec/domain/context`.

#### memory

| Event                        | Producer | Visibility | Posture          |
| ---------------------------- | -------- | ---------- | ---------------- |
| `memory.observation.saved`   | memory   | CLUSTER    | commit-then-emit |
| `memory.observation.deleted` | memory   | CLUSTER    | commit-then-emit |

**Detailed entries:** see `project/spec/domain/memory`.

#### agent_runtime

| Event                               | Producer      | Visibility | Posture                                                                                          |
| ----------------------------------- | ------------- | ---------- | ------------------------------------------------------------------------------------------------ |
| `agent_runtime.session.started`     | agent_runtime | CLUSTER    | LISTEN/NOTIFY (after batched write commits)                                                      |
| `agent_runtime.session.updated`     | agent_runtime | CLUSTER    | LISTEN/NOTIFY (batched, may carry many sessions in one event payload)                            |
| `agent_runtime.session.ended`       | agent_runtime | CLUSTER    | LISTEN/NOTIFY (urgent-flushed; payload includes native_file_path for session_mirrors extraction) |
| `agent_runtime.operation.completed` | agent_runtime | CLUSTER    | commit-then-emit                                                                                 |
| `agent_runtime.agent.restarted`     | agent_runtime | CLUSTER    | commit-then-emit (emitted after a successful in-place agent CLI restart)                         |

`agent_runtime.restart.failed` — Producer: agent_runtime. Visibility: LOCAL. Posture: commit-then-emit. Emitted at each restart-failure exit (kill-side abort, target agent disabled, self-restart readiness timeout); an actionable operator notification whose external delivery is debounced per session. See `project/spec/domain/agent_runtime` for the payload.

<!-- planned:todo-notify-owner -->

`agent_runtime.owner.notified` — Producer: agent_runtime. Visibility: LOCAL. Posture: commit-then-emit. Emitted when an agent working a todo invokes `telec todo notify`; an actionable notification addressed to the todo's owner, delivered to that principal's resolved channel rather than the admin fan-out. Carries no idempotency key — every invocation is a distinct ephemeral push. See `project/spec/domain/agent_runtime` for the payload.

<!-- /planned:todo-notify-owner -->

Note: agent_runtime uses windowed batched writes + LISTEN/NOTIFY dispatch for the high-volume hook-driven events (started/updated/ended). See `feature/agent_runtime/windowed-batch-write-and-dispatch`.

**Detailed entries:** see `project/spec/domain/agent_runtime`.

#### session_mirrors

| Event                            | Producer        | Visibility | Posture                                                               |
| -------------------------------- | --------------- | ---------- | --------------------------------------------------------------------- |
| `session_mirrors.mirror.created` | session_mirrors | CLUSTER    | commit-then-emit (first window for a session — INSERT)                |
| `session_mirrors.mirror.updated` | session_mirrors | CLUSTER    | commit-then-emit (subsequent windows — UPDATE appending text_content) |

**Detailed entries:** see `project/spec/domain/session_mirrors`.

#### integration

| Event                              | Producer    | Visibility | Posture          |
| ---------------------------------- | ----------- | ---------- | ---------------- |
| `integration.inbox.received`       | integration | CLUSTER    | inbox / relay    |
| `integration.outbox.appended`      | integration | CLUSTER    | commit-then-emit |
| `integration.outbox.delivered`     | integration | CLUSTER    | commit-then-emit |
| `integration.outbox.dead_lettered` | integration | CLUSTER    | commit-then-emit |

`integration.inbox.received` has two producers with the same channel, CLUSTER visibility, payload vocabulary, and idempotency semantics:

- **Durable messaging inbox (`inbox` posture):** external messaging webhooks that require durable capture write an inbox row first, then publish.
- **Stateless webhook ingress relay (`relay` posture):** the daemon-hosted ingress verifies and normalizes provider webhooks, then emits directly with the provider delivery id as `entry_id` and idempotency key. It relays every verified event regardless of the ingress node's own role or reaction.

Note: `integration.inbox.agent_hook_received` was REMOVED in the agent_runtime/integration boundary correction. Agent CLI hooks bypass integration entirely — they reach agent_runtime directly via the `telec-hook` subprocess (owned by agent_runtime). Integration's inbox is for true external webhooks only (Telegram, Discord, WhatsApp, GitHub).

**Detailed entries:** see `project/spec/domain/integration`.

#### reconciliation

| Event                                  | Producer       | Visibility | Posture                                                              |
| -------------------------------------- | -------------- | ---------- | -------------------------------------------------------------------- |
| `reconciliation.capability.advertised` | reconciliation | CLUSTER    | rides the cluster heartbeat (self-reported version + capability set) |

| Event                                        | Producer       | Visibility | Posture                                                                                  |
| -------------------------------------------- | -------------- | ---------- | ---------------------------------------------------------------------------------------- |
| `reconciliation.installation.drift_detected` | reconciliation | CLUSTER    | commit-then-emit (a relayed release matches this node's channel policy)                  |
| `reconciliation.installation.converged`      | reconciliation | CLUSTER    | commit-then-emit (the node is running and healthy on the target version)                 |
| `reconciliation.convergence.failed`          | reconciliation | CLUSTER    | commit-then-emit (a convergence step halts; carries `failed_step` and `failure_context`) |

`reconciliation.installation.drift_detected` carries `computer`, `channel`, `current_version`, `desired_version`, and `reason`.
`reconciliation.installation.converged` carries `computer`, `channel`, `from_version`, `to_version`, and `converged_at`.
`reconciliation.convergence.failed` carries `computer`, `run_id`, `from_version`, `to_version`, `failed_step`, and `failure_context`.

The convergence loop consumes `integration.inbox.received` (release/version subset, relayed by the single ingress), evaluates each release against the node's channel policy, and runs an exactly-once `ConvergenceRun` per target version. Desired-state config (`channel`, `pinned_minor`) is re-read on the loop's periodic self-check; the `config.effective.updated` event-driven path is deferred until a producer exists (the event is reserved, not yet emitted). `reconciliation.capability.advertised` is already current — it rides the cluster heartbeat the fleet capability map consumes.

**Detailed entries:** see `project/spec/domain/reconciliation`.

#### scheduler (infrastructure crate, not a service)

| Event                   | Producer        | Visibility | Posture                                                          |
| ----------------------- | --------------- | ---------- | ---------------------------------------------------------------- |
| `scheduler.tick.minute` | scheduler clock | CLUSTER    | commit-then-emit (the daemon emits one generic minute tick)      |
| `scheduler.tick.hour`   | scheduler clock | CLUSTER    | derived — fires on the minute-tick that crosses an hour boundary |
| `scheduler.tick.day`    | scheduler clock | CLUSTER    | derived — fires on the minute-tick that crosses a day boundary   |

The scheduler clock is an in-daemon periodic emitter, not a host-level service configuration or per-task timer. It emits the generic events above; per-pillar listeners subscribe and consult their own cadence policy + cursor state to decide whether to act. NOT a bounded context; infrastructure only.

### Subscription map

Inverse view: for each event, which consumers act on it. Populated as per-context specs land.

| Event | Consumers |
| ----- | --------- |

| `integration.inbox.received` | `agent_runtime` (routes inbound EXTERNAL messages to sessions; e.g., Telegram inbound); `reconciliation` (release/version subset) |

| `agent_runtime.session.started` | `frontend` (live UI), audit log consumers |
| `agent_runtime.session.updated` | `frontend` (live UI, iterates batched payload), `telec-tui` (cache invalidation) |
| `agent_runtime.session.ended` | `session_mirrors` (extracts mirror from native_file_path), `identity` (auto-revokes session token), `frontend` (live UI removal) |
| `session_mirrors.mirror.created` | `frontend` (history search index refresh), audit log consumers |
| `agent_runtime.operation.completed` | `workflow` (advances todo phase when operation completes a step) |
| `workflow.todo.phase_advanced` | `integration` (outbox notifications to recipients per subscription) |
| `workflow.todo.delivered` | `integration` (delivery announcement notifications) |
| `workflow.todo.renamed` | `frontend` (re-key roadmap/todo view old→new), `telec-tui` (cache invalidation — drop old_slug, refetch new_slug), `integration` (slug-keyed subscription bookkeeping) |
| `memory.observation.saved` | audit log consumers; future memory miner correlating observations |
| `scheduler.tick.minute` | per-pillar listeners (skill mining, memory mining, job-completion sweeps, etc.) |
| `config.effective.updated` | every service that caches config (re-read on next access) |

Additional runner subscriptions:

| Event                          | Consumers                                                                                                                                                                                                                    |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workflow.todo.created`        | `workflow.lifecycle_runner` (reload affected project and dispatch eligible unheld entries; v1 source already exists)                                                                                                         |
| `workflow.todo.updated`        | `workflow.lifecycle_runner` (re-evaluate when hold, dependency, kind, artifact, or phase-adjacent metadata changes; v1 source must be wired where absent)                                                                    |
| `workflow.todo.phase_advanced` | `workflow.lifecycle_runner` (re-evaluate when prepare/work gates advance; v1 source is the generalized phase-transition seam, while `integration` remains the finalize-ready handoff owner)                                  |
| `workflow.todo.delivered`      | `workflow.lifecycle_runner` (re-evaluate downstream dependents after a dependency reaches delivery; v1 delivery emission/bridge is part of this delivery)                                                                    |
| `workflow.roadmap.entry_moved` | `workflow.lifecycle_runner` (re-evaluate after dependency, icebox, unfreeze, or delivery movement; v1 mutation emissions/bridges are part of this delivery)                                                                  |
| `config.effective.updated`     | `workflow.lifecycle_runner` (invalidate autostart policy and re-evaluate affected project/global scope; v1 config watcher is the seam)                                                                                       |
| `agent_runtime.session.ended`  | `workflow.lifecycle_runner` (wake-up: re-evaluate the closed session's todo and clear the now-stale `active_runner` link; a manual close's hold is set at the close command, not inferred here; v1 `SESSION_CLOSED` bridged) |

Task-lane runner subscriptions:

| Event                   | Consumers                                                                                                                                                                        |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workflow.todo.updated` | `workflow.lifecycle_runner` (re-evaluate when a task's `task-plan`, authorization stamp, schedule, hold, or dependency/schedule gate changes)                                    |
| `scheduler.tick.minute` | `workflow.lifecycle_runner` (re-evaluate tasks whose optional schedule may now be due; the tick never carries task identity and never creates a persisted timer claim by itself) |

The task schedule flow is wake-up-driven rather than timer-state-driven: the daemon scheduler clock emits the generic minute tick, workflow reloads the project todo set, and the lifecycle runner dispatches only tasks that still pass authorization, hold, live-session/claim, and schedule/dependency eligibility at evaluation time. For a recurring task that already has a live run session, the runner dispatches nothing further — the live session suppresses a concurrent second firing; when no live run session exists at a due tick, the runner dispatches a fresh `/next-run-task`, never signalling a live session.

### v1 → v2 event-name mapping

Canonical reference for translating v1 event names found in v1 feature
snippets into v2 names. Used by the `v1-to-v2-snippet-port` instruction set
(rule 4). When the v2 name is fixed, the porting agent substitutes directly.
When marked **TBD**, the agent describes the event semantically in the v2
spec body and flags it for catalog completion.

#### Direct renames

| v1 event name                                              | v2 event name                                                           |
| ---------------------------------------------------------- | ----------------------------------------------------------------------- |
| `domain.software-development.planning.todo_finalize_ready` | `workflow.todo.phase_advanced` (with `phase=finalize_ready` in payload) |
| `agent_runtime.session.spawn`                              | `agent_runtime.session.started`                                         |
| `agent.restart_dispatched`                                 | `agent_runtime.agent.restarted`                                         |

#### v1 event contracts that are catalog-tracked (exception to the "v1 names not in catalog" rule)

The catalog's general rule is that v1 names are NOT included — they are
carried through the v1→v2 ACL with translation. The exception below
records a v1 event whose contract was elevated into the catalog because
the v1 emission boundary itself is the durable design surface for an
in-flight delivery and the v1→v2 mapping row alone does not pin the v1
payload, posture, or emission boundary.

##### `domain.software-development.planning.todo_finalize_ready` (v1)

- **Producer:** `workflow` (v1 Python `TodosDb`)
- **Emitted when:** the v1 `TodosDb` write-state chokepoint observes a
  lifecycle-phase transition `* → finalize_ready` on an owned-session
  commit (the work-machine claim, or any future writer that lands the
  phase through the same chokepoint).
- **Payload (domain-named):** `slug`, `branch`, `sha`,
  `worker_session_id`, `ready_at`.
- **Known consumers:** `IntegrationTriggerCartridge` (spawns the
  singleton integrator session for the slug).
- **Visibility:** `LOCAL` (single-host Redis scope).
- **Idempotency key:** `(slug, sha, worker_session_id)`, matching the
  cartridge's existing dedup set.
- **Posture:** `commit-then-emit` — the chokepoint hook fires after the
  TodosDb write commits successfully.
- **v2 mapping:** see the v1→v2 Direct renames table above; the v2
  representation is `workflow.todo.phase_advanced` with
  `phase=finalize_ready` in the payload.
- **Why it lives here:** the chokepoint design centralizes v1 emission
  for this event. Recording the v1 contract in the catalog gives
  cross-context discoverability for the cartridge consumer and pins
  the payload, posture, and emission boundary. The "v1 names not in
  catalog" caveat in Known Caveats now cites this entry as the
  explicit exception.

#### Internal v1 tokens (not events — describe semantically)

In-process tokens or hook names from v1, not cross-process events. Describe
their semantic intent in v2 spec bodies rather than naming them.

| v1 internal token   | v2 semantic description                                              |
| ------------------- | -------------------------------------------------------------------- |
| `AGENT_READY`       | "the agent signals readiness after startup"                          |
| `_on_mutation`      | "state mutation notification" (replaced by Redis subscription in v2) |
| `SessionStart` hook | "agent CLI lifecycle hook fired at session start"                    |
| `SIGTERM` to PID    | "agent process terminated cleanly"                                   |

#### TBD — v2 owner not yet decided

These v1 events belong to the workflow integrate-lifecycle (merging
delivered branches into main) which v2 has not finalized as either a
workflow-pillar concern or a separate concern. Until the v2 integrate-phase
design lands, the porting agent describes these events semantically in v2
spec bodies and flags them for catalog completion.

| v1 event name                          | v2 owner (TBD)           | Semantic intent                                                       |
| -------------------------------------- | ------------------------ | --------------------------------------------------------------------- |
| `integration.candidate.committed`      | workflow integrate-phase | "a branch is committed and queued for integration into main"          |
| `integration.candidate.dequeued`       | workflow integrate-phase | "an integration candidate is removed from the queue without merging"  |
| `integration.candidate.blocked`        | workflow integrate-phase | "an integration candidate is blocked pending resolution"              |
| `integration.candidate.already_merged` | workflow integrate-phase | "an integration candidate's branch is already part of main; no-op"    |
| `integration.candidate.delivered`      | workflow integrate-phase | "an integration candidate has been successfully delivered"            |
| `integration.merge.succeeded`          | workflow integrate-phase | "a branch was merged into main successfully"                          |
| `integration.merge.conflicted`         | workflow integrate-phase | "a merge attempt failed due to conflicts"                             |
| `integration.push.succeeded`           | workflow integrate-phase | "a push to origin/main succeeded"                                     |
| `integration.push.rejected`            | workflow integrate-phase | "a push to origin/main was rejected (non-fast-forward or hook block)" |
| `integration.started`                  | workflow integrate-phase | "the integration process began for a delivered candidate"             |

The v2 `integration` bounded context owns external boundaries (Telegram,
Discord, WhatsApp, GitHub webhooks). The events above belong to the workflow
integrate-phase, NOT to the v2 `integration` pillar. The v1 naming overlap
is incidental.

## Allowed values

- `visibility`: `LOCAL` (single-host Redis scope — events confined to this computer), `CLUSTER` (single-owner mesh Redis scope — cross-host within one user's fleet), `PUBLIC` (federation hub Redis scope — cross-mesh). Three real Redis client instances in v2; routing is explicit per envelope. See `project/design/architecture-v2/event-bus-transports` for the bus semantics. Single-computer installs run Local-only; emits to Cluster/Public silently drop when those scopes aren't configured.
- `posture` (emit safety pattern): `commit-then-emit` (the producer commits its state change in Postgres, THEN publishes the event; loud-fail on publish failure — caller treats it as a defect since the state change already landed), `outbox` (the event is written to the producing context's outbox table atomically with the caller's state change; a dispatcher publishes asynchronously — used for outbound external delivery and for cross-context events where at-least-once matters), `inbox` (the event represents an external input captured durably first then published; used for ingress paths from external systems whose drops cannot be re-derived), `relay` (the producer verifies and normalizes an external input and emits immediately without durable ingress state; the event's idempotency key lets consumers absorb provider replays).

## Known caveats

- This catalog is `actual` upon commit and evolves with every per-context spec edit.
- The producer context's per-context spec is the authoritative source for event payload field names; this catalog summarizes for cross-context discoverability. If they disagree, the per-context spec wins and this catalog gets corrected in the same PR.
- Events not in this catalog don't exist. An emitter trying to publish an event not in the catalog is a defect — register it here first, in the same PR.
- v1 events that don't fit the v2 naming convention will be carried through the v1→v2 ACL with translation. The ACL maps v1 event names to v2 catalog entries. v1 names are NOT included in this catalog, with one explicit exception captured under "v1 event contracts that are catalog-tracked": `domain.software-development.planning.todo_finalize_ready`, whose v1 contract is recorded here because the v1 emission boundary itself is the durable design surface for an in-flight delivery.
- Event payload schemas live in the producing context's spec, not here. This catalog gives the name + the field set in domain terms; the per-context spec gives the wire schema.
- Consumer lists in the subscription map are aspirational pending per-context spec authoring. They're listed here so cross-context coordination is visible from one place.
- The v1 → v2 mapping subsection in "Canonical fields" is the authoritative reference for the v1→v2 snippet port (rule 4 of `v1-to-v2-snippet-port`). When a v2 name is marked TBD, the porting agent describes the event semantically in the v2 spec body and flags it for catalog completion later.

Note: the **v2 `integration` bounded context** owns external boundaries
(Telegram, Discord, WhatsApp, GitHub webhooks). The events above belong to
the workflow integrate-phase, NOT to the v2 `integration` pillar. The
v1 naming overlap is incidental.
