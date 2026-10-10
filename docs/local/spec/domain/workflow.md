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
- **Implementation roots:** `teleclaude/core/todos_db/`,
  `teleclaude/core/next_machine/`, `teleclaude/core/integration/`, and todo CLI
  handlers.
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
- **Also owns:** the names of the todo-lifecycle commands — one
  domain-qualified value each — and its own emissions of them: dispatch
  requests, machine scripts, and procedure loads. A command whose meaning
  belongs to another context is named by that context; the shared name table in
  the codebase holds every value mechanically and confers no authority. The
  corpus those names are laid out in belongs to `context`; resolving a name to a
  document, the session record and title that carry it, and the live-session
  attribution query that matches it belong to `agent_runtime`, which this
  context consumes.

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

## See Also

- docs/local/spec/feature/workflow/blueprint-freshness.md —
  canonical-main maintenance coordination for the shared Blueprint baseline.

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered project, person, or company its act happened in.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.

- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why each event names the thing it is about as its subject, separately from its origin.
- docs/local/adr/0117-a-platform-event-type-names-the-state-it-reports.md — why the subject of an event that reports a state is the thing whose state it is.

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
