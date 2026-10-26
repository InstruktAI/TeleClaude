---
visibility: internal
description: Frozen v1 ownership anchor for todos, artifacts, lifecycle state, and integration workflow.
---

# Workflow Domain Spec — Spec

## What it is

The v1 workflow area owns todo records, roadmap status, preparation artifacts,
lifecycle state, claims, worktree delivery, and integration coordination. Its
feature specs remain the current contract.

## Canonical fields

- **Current behavior:** `docs/local/spec/feature/workflow/`.

- **Implementation roots:** `teleclaude/core/workflow_store/` owns the
  backend-neutral workflow-store contract, selection, and the local and GitHub
  adapters; `teleclaude/core/todos_db/` remains the SQLite implementation and
  migration owner that both adapters serve the port through, the GitHub adapter
  on its working copy. `teleclaude/core/next_machine/`,
  `teleclaude/core/integration/`, API routes, services and CLI handlers consume
  the workflow-store contract and do not access a backend directly.

- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. Replacement work never uses this store or
  lifecycle.

### Ownership boundary

- **Owns:** todo and artifact records, preparation and delivery state
  transitions, claims, dependencies, worktree delivery, and integration
  coordination.
- **Does not own:** agent process lifecycle, provider transport, caller
  identity, or domain behavior delivered by a todo.
- **Published contracts:** todo and artifact commands, queries, lifecycle
  events, and explicit dispatch requests to agent runtime.
- **Also published:** where a project's shared state lives, given a project
  root. A primary checkout owns its own state and a linked worktree's state
  lives at the owning checkout — the relation this context creates and defines,
  which is why the answer is published from here rather than from the context
  that owns the project's configuration file. Consumers read it through this
  contract and never interpret git metadata themselves.
- **Also published:** which checkouts are slug worktrees and where a slug
  worktree's home lives, given the worktree root
  (`local/projects/teleclaude/spec/feature/agent_runtime/isolated-home`). The contract loads no
  other part of the platform, so runtime home resolution can ask it before
  anything else loads. Consumers ask this contract and never restate the
  layout.

- **Also owns:** which entry procedure each todo-lifecycle dispatch names —
  the prepare and work overviews, the build, review, finalize, drift-analysis,
  task and deferral procedures — and every emission of those procedure IDs by
  the lifecycle state machines and the lifecycle runner; and the lane
  groupings of catalog role names its own gates read: the preparation-authoring
  roles (prepare-orchestrator, intaker, architect, diagnoser, planner), the
  worktree-writer roles (builder, finalizer) and the work-lane roles
  (work-orchestrator and the writers). The artifact-authority gate, kickback
  stamping and the checkpoint's worktree dirty-set selection consume those
  groupings by role name; the catalog composes the roles and decides nothing
  about lanes (`local/projects/teleclaude/spec/feature/identity/agent-roles`).

- **Also owns (failed-check bugs):** the filer that turns failed required CI
  checks into bugs
  (`local/projects/teleclaude/spec/feature/workflow/failed-check-bugs`). One
  platform event consumer on each computer is handed the run completed events
  its own computer emitted, so each run is filed once in the cluster, by the
  computer whose store receives the bug. For each failure of a red
  required-check run on main or on a dependency-update branch, it finds the open
  bug that carries the failure's fingerprint. When none exists, it creates the
  bug through the creation transaction, under the platform's system principal
  (`local/projects/teleclaude/spec/feature/workflow/todo-creation`).
- **Also owns (the `check-failures` artifact):** a filed bug's record of its
  failures, occurrences and recoveries. It is append-only, and the filer is its
  only writer, keying each entry by run, attempt and job so a repeated handling
  appends nothing. Earlier entries never change, so a session that has claimed
  the bug and read the record is never invalidated by a later append. The filer
  never writes the bug's `input`, `log` or any other artifact. Like `log`,
  `check-failures` is not prepare-owned, not drift-tracked and not
  lifecycle-relevant; preparation discovers it with the bug's other artifacts.
  A green required-check run on a branch appends that branch's recovery to every
  open bug whose record holds a failure of that check on that branch since its
  last recovery there.

### Preparation completion provenance

Every transition into PREPARED records the completing prepare orchestrator's
TeleClaude session id as `prepared_session_id`. The prepare orchestrator is a
TeleClaude session by contract, so absence of that identity is a contract
violation: the transition fails before PREPARED or provenance persists. A
later preparation pass replaces the value through the same boundary. Claims,
artifact writes, review verdicts, and intermediate phases never set it.

Todo state advances to schema v13 through one forward migration. The upcycle
entrypoint retains the persisted source version across sequential hops. The
v12-to-v13 migration seeds `prepared_session_id` only when the source version
was exactly v12, the record is currently PREPARED, and `active_runner` carries
the authoritative completing session. A record merely passing through v12
from an older schema, a later-stage record, or a record without that exact
evidence stays unstamped. Domain consumers see only the v13 shape.

The Todo query projection publishes `prepared_session_id` and an
`artifact_updated_at` mapping keyed by artifact name. Timestamps come from the
current artifact records. The existing `files` list remains the ordered
artifact-name contract.

This placement follows `sdlc/policy/domain-ownership`:
workflow records and publishes its facts once, while presentation consumers
never reconstruct lifecycle or artifact policy.

### Event subjects and origins

Every platform event workflow emits states as its subject and origin what its act
concerned:

- todo lifecycle, roadmap, preparation, build, review, integration, and delivery
  events: the todo or delivery they concern, with the project it belongs to as
  origin;
- deployment events: the deployed project's deployment, one thing across all
  its deployments, with the deployed project as origin;
- the schedule clock's minute tick: the computer whose clock ticked, with no
  origin.

### Governing designs and decisions

- **local/projects/teleclaude/design/architecture/integration-state-machine** — Phase C state machine: lease-serialized, crash-recoverable integration from feature branches to canonical main.
- **local/projects/teleclaude/design/architecture/lifecycle-state-machines** — Overview of the three state machines that drive the TeleClaude software development lifecycle.
- **local/projects/teleclaude/design/architecture/next-machine** — Stateless state machine for orchestrating multi-phase project workflows.
- **local/projects/teleclaude/design/architecture/prepare-flow** — Prepare phase flow for PRD → Architecture → Plan → Prepared, with PRD-only human approval, reviewer-gated derivation artifacts, size-based architecture skipping, and lean drift analysis.
- **local/projects/teleclaude/design/architecture/work-state-machine** — Phase B state machine: build, review, fix, and finalize routing for implementation work. Terminal phase is finalize_ready; the integration event is emitted by the TodosDb write-state chokepoint on any lifecycle-phase write, not from within the work-step.
- **local/projects/teleclaude/design/architecture/workflow-store** — Backend-neutral port, local adapter and GitHub adapter boundary for workflow records, operations, and integration.
- **local/projects/teleclaude/adr/0001-git-stash-prevention** — Phantom git stash entries from test runs and stale worktree wrappers blocked the work state machine; resolved via test-isolation, worktree-preferring state IO, defense-in-depth autostash prevention, and a three-tier git permission model.
- **local/projects/teleclaude/adr/0015-kind-as-lifecycle-entry-point** — A kind names the lifecycle entry point: the SDLC kinds (feature/change/bug), the non-SDLC `task` kind, and an optional kind at intake (kind-less dumps are classified and auto-assigned by /analyze-todo-input).
- **local/projects/teleclaude/adr/0017-review-lanes-as-dod-anchored-shared-group** — Review lanes are extracted into one DoD-anchored shared catalog that the build reviewer, commit reviewer, and planner all reference, instead of being embedded in the build-review procedure and re-described in the plan reviewer.
- **local/projects/teleclaude/adr/0019-bug-lane-diagnosis-gate** — Bugs enter a mandatory diagnosis prepare stage and reuse the change plan→plan-review→build pipeline, replacing the no-prepare fix lane.
- **local/projects/teleclaude/adr/0020-upstream-how-is-a-hypothesis-not-a-gate** — Mechanism (HOW) named in upstream intent is a verifiable hypothesis the consuming author overrides against code reality, not a directive — and not something a creation-time gate rejects.
- **local/projects/teleclaude/adr/0021-remove-reconcile-and-mark-phase** — Removed the telec todo reconcile and mark-phase commands and the mechanical-invalidation subsystem; lifecycle_phase derives from evidence on dispatch, and drift materiality stays an intelligence judgment.
- **local/projects/teleclaude/adr/0033-doc-only-commits-require-independent-review** — A doc-only commit that changes a doc snippet is not review-exempt: it requires an independent fast/medium doc-hygiene commit-review on the committed SHA. The authoring agent may never review a snippet it wrote, because it believes its own work is correct. The check is narrow and cheap — the doc-hygiene lane over one or two changed snippets — so enforcing it costs little.
- **local/projects/teleclaude/adr/0035-active-runner-driver-ownership** — A todo's lifecycle driver is owned by a durable session-id link the dispatcher writes, verified lazily against the live-session ledger — not inferred from session titles.
- **local/projects/teleclaude/adr/0036-manual-close-is-an-explicit-halt** — A manual session close halts its todo via an explicit hold set at the close command; the runner self-heals the active_runner link. No close-intent taxonomy is stamped on the close event.
- **local/projects/teleclaude/adr/0042-task-lane-decoupled-recurring-self-bookkeeping** — The task lane is decoupled from the SDLC prepare machine: two runner-routed agent runs (draft-plan, run) gated by human authorization, recurrence via a schedule reusing the durable task-plan, ephemeral runs over a durable todo, self-bookkeeping via a continuity log, and a predictable durable workspace output home.
- **local/projects/teleclaude/adr/0046-spec-anchored-testing** — Testing moves from agent-authored unit tests (1:1 source mapping, TDD iron-law) to spec-anchored behavioral tests that bind human-authored feature-spec scenarios. No agent unit tests where no compiler enforces correctness; functional + smoke levels; coverage measured against the scenario inventory; spec-mirrored test files; fingerprint-based drift detection.
- **local/projects/teleclaude/adr/0048-diagnosis-records-cause-not-fix** — The bug DIAGNOSE phase grounds the root cause and prescribes no fix; evidence and conclusion become separate artifacts. Reverses ADR 0019's fix-prescription clause.
- **local/projects/teleclaude/adr/0051-task-run-is-persistent** — A /run-task session is persistent — it executes against the durable task-plan, records to the log, delivers to the workspace, and stays alive for human follow-up and subsequent scheduled firings; the lifecycle runner wakes the live session on each due tick rather than spawning a fresh ephemeral run. Supersedes ADR-0042 §5 (ephemeral-and-terminate); the rest of ADR-0042 stands.
- **local/projects/teleclaude/adr/0052-orchestrator-dedup-registry-authoritative** — Orchestrator dedup is registry-authoritative on the structured working_slug + orchestrator system_role fields; active_runner is demoted from sole dedup authority to the gate-approval/lane-handoff pointer and remains the dedup signal for non-orchestrator (task) drivers. Amends ADR-0035.
- **local/projects/teleclaude/adr/0053-hold-scoped-to-autostart-enabled-kinds** — Hold applies only while a todo kind's autostart policy is enabled; autostart-disabled kinds do not write, render, or offer hold.
- **local/projects/teleclaude/adr/0056-roleless-sessions-exempt-from-prepare-write-role-gate** — Prepare-artifact write authority exempts roleless (human-originated) sessions from the role allowlist and governs them by the live-holder claim; a manual lifecycle invocation on an unheld todo claims it in-process rather than spawning an orchestrator.
- **local/projects/teleclaude/adr/0057-spec-coverage-enforcement-by-review** — Spec-anchored coverage and structure are enforced by the build-review reviewer and the spec → test → code change process, not by automated tooling. The per-scenario content-fingerprint drift mechanism and an automated spec-structure/coverage gate (a validator wired into telec sync and pre-commit) are not adopted.
- **local/projects/teleclaude/adr/0060-task-firing-outcome-contract** — A task firing reports a durable outcome that the lifecycle runner reconciles into the todo's terminal state — success delivers a one-shot (records and stays live for a recurring), error holds with a reason and keeps the run session alive as the beacon. The outcome is a durable stamp on the lifecycle-runner + todo-state substrate, not an ephemeral event, and adds no new TodoState field; recovery from an error-hold is talk-to-stamp-success or a deliberate manual start, never a bare unhold. Supersedes ADR-0051 in part.
- **local/projects/teleclaude/adr/0061-hold-is-durable-dispatch-brake** — Hold is the durable autonomous-dispatch brake for any active todo; manual close and explicit hold requests persist it independently of kind, phase, and autostart policy.
- **local/projects/teleclaude/adr/0063-task-runs-are-ephemeral** — A /run-task firing is ephemeral: it executes, records, stamps its outcome, and ends on success — recurrence is the lifecycle runner spawning a fresh run at each due scheduler tick, not waking a live session. Removes the persistent successful-run beacon and the runner-wakes-the-live-session signalling; the errored-firing hold-and-stay-alive beacon is retained. Supersedes ADR-0051; supersedes in part ADR-0060; restores ADR-0042 §5.
- **local/projects/teleclaude/adr/0065-integrator-parks-and-drains-with-integrity-only-gating** — The integrator delivers by park-and-drain with integrity-only pre-push gating; its authority ends at the push, and post-push steps only confirm, record, and clean up.
- **local/projects/teleclaude/adr/0067-authorization-reads-the-object-not-the-caller-role** — Authorization for todo and artifact mutation derives from the object — the live-holder claim and the lifecycle phase — plus the operation set a session brief includes. The caller-role allowlist is retired; the self-restart and self-end carve-outs collapse into ownership.
- **local/projects/teleclaude/adr/0075-cutover-bearing-delivery-is-not-partitioned** — A rework whose cutover must be seeded before any new-code emission is delivered unified; coherence, not file count, decides whether it is partitioned.
- **local/projects/teleclaude/adr/0076-integrator-parks-blockers-and-keeps-quality-gating** — The integrator parks undeliverable candidates while retaining the complete deterministic pre-push quality gate as a blocker.
- **local/projects/teleclaude/adr/0078-remove-time-bound-dispatch-reservations** — Lifecycle dispatch records ownership directly and carries no time-bound reservation before or beside active ownership.
- **local/projects/teleclaude/adr/0081-commit-scope-is-the-sole-foreign-ownership-predicate** — Conventional-commit scope is the only predicate that parks a candidate for foreign ownership; a touched path outside the plan's referenced-paths contract becomes ambiguity evidence instead.
- **local/projects/teleclaude/adr/0082-candidate-span-ownership-inspection-is-withdrawn** — Span-ownership inspection is removed from the integrator; the contamination it guarded against is prevented by worktree isolation and was never observed.
- **local/projects/teleclaude/adr/0085-canonical-doc-state-before-delivery** — Publish committed repo-root documentation state before candidate selection, keep one candidate delivery fold, and repair exceptional settled-marker divergence as a separate operation.
- **local/projects/teleclaude/adr/0089-delivery-folds-on-repository-root-main** — Use repository-root main as the sole documentation-fold and final-push surface for candidate delivery.
- **local/projects/teleclaude/adr/0090-root-fold-finalizes-a-pushed-candidate** — Finalize a confirmed integration-worktree push by synchronizing, folding, and publishing repository-root main before recording delivery.
- **local/projects/teleclaude/adr/0091-published-candidate-finalization-blocks-the-drain** — Preserve parking before candidate publication and block the drain on unresolved repository-root finalization after publication.
- **local/projects/teleclaude/adr/0092-divergence-detection-belongs-to-the-acting-role** — Marker-divergence detection runs inside the role that repairs it, replacing an unattended periodic sweep that faulted to a log.
- **local/projects/teleclaude/adr/0096-claimed-todo-artifacts-are-writable-only-by-the-claiming-group** — A claimed todo's artifacts are writable only by the session holding the claim and the sessions it dispatched, across every writable artifact kind.
- **local/projects/teleclaude/adr/0104-every-todo-is-created-with-its-kind** — A todo's kind is supplied by whoever files it and is required at creation; there is no kindless intake and no autonomous classification step.
- **local/projects/teleclaude/adr/0125-github-store-keeps-the-local-implementation-as-its-working-copy** — The GitHub workflow-store adapter serves the port through the existing local implementation as a disposable working copy and writes every change to GitHub before the local commit completes, instead of reimplementing the port's operations against the GitHub API.
- **local/projects/teleclaude/adr/0126-non-repository-work-stays-in-the-github-store-working-copy** — On a GitHub-backed project, tasks and creative-track items are kept in the GitHub store's working copy as that computer's own record and never published, instead of being published as issues or served from a second, local store beside the GitHub one.

## See Also

- docs/local/spec/feature/workflow/blueprint-freshness.md —
  canonical-main maintenance coordination for the shared Blueprint baseline.

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered project, person, or company its act happened in.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.

- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why each event names the thing it is about as its subject, separately from its origin.
- docs/local/adr/0117-a-platform-event-type-names-the-state-it-reports.md — why the subject of an event that reports a state is the thing whose state it is.

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
