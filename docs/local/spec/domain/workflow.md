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

<!-- planned:github-item-acts -->

- **Also owns (item title):** an item's title — the readable name a person
  gives it, apart from its slug, set or cleared through the update facade and
  held with the item's row facts. Setting it changes nothing else about the
  item; a store that shows the item uses it where it shows a title.

<!-- /planned:github-item-acts -->

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

<!-- planned:task-firing-timestamp-line -->

- **Also owns (the task firing line):** the `log` of a `kind=task` todo records
  when each of its firings started. Every firing appends exactly one line,
  `[HH:MM:SS-DD/MM] execution`, to the end of the task's `log`: the instant the
  firing started, read from the system clock and rendered as 24-hour time and
  day/month in the computer's configured timezone (`computer.timezone`,
  `local/projects/teleclaude/spec/teleclaude-config`). A firing starts when the
  task-run lane accepts a fresh run session for the task — from a lifecycle
  runner dispatch or a manual start — or continues a firing in place in the
  session already driving it. The line is appended as soon as that start is
  accepted, before the driver claim is recorded. A dispatch that starts no
  session, or that records a session an earlier dispatch already started,
  appends nothing. A failure to append the line is logged and leaves the firing
  running. The run session keeps every firing line verbatim
  (`sdlc/procedure/lifecycle/task/run-task`); the platform never writes any
  other part of the `log`.

<!-- /planned:task-firing-timestamp-line -->

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

- `local/projects/teleclaude/design/architecture/integration-state-machine` — integrating finished work into canonical main
- `local/projects/teleclaude/design/architecture/lifecycle-state-machines` — the three machines that drive the lifecycle
- `local/projects/teleclaude/design/architecture/next-machine` — the stateless orchestration machine
- `local/projects/teleclaude/design/architecture/prepare-flow` — the prepare phase from intent to prepared
- `local/projects/teleclaude/design/architecture/work-state-machine` — build, review, fix and finalize routing
- `local/projects/teleclaude/design/architecture/workflow-store` — the workflow store port and its local and GitHub adapters
- `local/projects/teleclaude/adr/0001-git-stash-prevention` — keeping test runs from leaving git stash entries
- `local/projects/teleclaude/adr/0015-kind-as-lifecycle-entry-point` — a kind as the lifecycle entry point
- `local/projects/teleclaude/adr/0017-review-lanes-as-dod-anchored-shared-group` — review lanes as one shared catalog
- `local/projects/teleclaude/adr/0019-bug-lane-diagnosis-gate` — the bug lane's diagnosis gate
- `local/projects/teleclaude/adr/0020-upstream-how-is-a-hypothesis-not-a-gate` — upstream mechanism as a hypothesis for the consuming author
- `local/projects/teleclaude/adr/0021-remove-reconcile-and-mark-phase` — removal of reconcile and mark-phase
- `local/projects/teleclaude/adr/0035-active-runner-driver-ownership` — durable ownership of a todo's lifecycle driver
- `local/projects/teleclaude/adr/0036-manual-close-is-an-explicit-halt` — a manual close halting its todo
- `local/projects/teleclaude/adr/0042-task-lane-decoupled-recurring-self-bookkeeping` — the task lane outside the prepare machine
- `local/projects/teleclaude/adr/0046-spec-anchored-testing` — spec-anchored testing
- `local/projects/teleclaude/adr/0048-diagnosis-records-cause-not-fix` — diagnosis recording the cause, not the fix
- `local/projects/teleclaude/adr/0051-task-run-is-persistent` — task runs as persistent sessions
- `local/projects/teleclaude/adr/0052-orchestrator-dedup-registry-authoritative` — orchestrator dedup through the registry
- `local/projects/teleclaude/adr/0053-hold-scoped-to-autostart-enabled-kinds` — hold limited to autostart-enabled kinds
- `local/projects/teleclaude/adr/0056-roleless-sessions-exempt-from-prepare-write-role-gate` — roleless sessions writing prepare artifacts
- `local/projects/teleclaude/adr/0057-spec-coverage-enforcement-by-review` — spec coverage enforced by review
- `local/projects/teleclaude/adr/0060-task-firing-outcome-contract` — task firings reporting a durable outcome
- `local/projects/teleclaude/adr/0061-hold-is-durable-dispatch-brake` — hold as the durable dispatch brake
- `local/projects/teleclaude/adr/0063-task-runs-are-ephemeral` — task firings as ephemeral runs
- `local/projects/teleclaude/adr/0065-integrator-parks-and-drains-with-integrity-only-gating` — the integrator's park-and-drain delivery
- `local/projects/teleclaude/adr/0067-authorization-reads-the-object-not-the-caller-role` — todo and artifact authorization read from the object
- `local/projects/teleclaude/adr/0075-cutover-bearing-delivery-is-not-partitioned` — delivering a cutover-bearing rework unpartitioned
- `local/projects/teleclaude/adr/0076-integrator-parks-blockers-and-keeps-quality-gating` — the integrator parking blockers while keeping quality gating
- `local/projects/teleclaude/adr/0078-remove-time-bound-dispatch-reservations` — dispatch recording ownership without time-bound reservations
- `local/projects/teleclaude/adr/0081-commit-scope-is-the-sole-foreign-ownership-predicate` — commit scope as the only foreign-ownership predicate
- `local/projects/teleclaude/adr/0082-candidate-span-ownership-inspection-is-withdrawn` — withdrawal of span-ownership inspection
- `local/projects/teleclaude/adr/0085-canonical-doc-state-before-delivery` — publishing canonical documentation state before candidate selection
- `local/projects/teleclaude/adr/0089-delivery-folds-on-repository-root-main` — repository-root main as the fold and push surface
- `local/projects/teleclaude/adr/0090-root-fold-finalizes-a-pushed-candidate` — finalizing a pushed candidate by folding root main
- `local/projects/teleclaude/adr/0091-published-candidate-finalization-blocks-the-drain` — blocking the drain on an unresolved published candidate
- `local/projects/teleclaude/adr/0092-divergence-detection-belongs-to-the-acting-role` — marker-divergence detection inside the repairing role
- `local/projects/teleclaude/adr/0096-claimed-todo-artifacts-are-writable-only-by-the-claiming-group` — claimed artifacts writable only by the claiming group
- `local/projects/teleclaude/adr/0104-every-todo-is-created-with-its-kind` — every todo created with its kind
- `local/projects/teleclaude/adr/0125-github-store-keeps-the-local-implementation-as-its-working-copy` — the GitHub store's working copy and push before local commit
- `local/projects/teleclaude/adr/0126-non-repository-work-stays-in-the-github-store-working-copy` — non-repository work kept in the GitHub store's working copy
- `local/projects/teleclaude/adr/0133-concurrent-driver-starts-serialize-in-process-at-the-start-doors` — concurrent driver starts for one todo serialized on one computer
- `local/projects/teleclaude/adr/0134-a-colliding-driver-start-is-refused-without-waiting` — a colliding driver start refused at once instead of waiting
- `local/projects/teleclaude/adr/0135-github-backed-driver-starts-are-admitted-by-the-mesh-master` — driver starts of a GitHub-backed project admitted by the fleet's master
- `local/projects/teleclaude/adr/0136-only-the-master-writes-a-github-backed-claim` — every write of a GitHub-backed claim made by the master
- `local/projects/teleclaude/adr/0137-a-github-backed-claim-is-settled-per-todo` — settling a GitHub-backed claim per todo: driver answers, ordered releases, reactivation
- `local/projects/teleclaude/adr/0138-a-filing-completes-after-its-request-under-a-receipt` — a filing returns a receipt and completes after its request, in its project's acceptance order
- `local/projects/teleclaude/adr/0147-a-review-runs-each-lane-in-a-fresh-native-subagent-under-a-judging-parent` — each review lane in a fresh native subagent under a parent that briefs, reconciles and judges the whole

## See Also

- docs/local/spec/feature/workflow/blueprint-freshness.md —
  canonical-main maintenance coordination for the shared Blueprint baseline.

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered project, person, or company its act happened in.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.

- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why each event names the thing it is about as its subject, separately from its origin.
- docs/local/adr/0117-a-platform-event-type-names-the-state-it-reports.md — why the subject of an event that reports a state is the thing whose state it is.

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
