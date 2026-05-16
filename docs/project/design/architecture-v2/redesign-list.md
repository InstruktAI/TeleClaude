---
description: 'Anti-patterns from v1 that v2 must NOT port. Living document — each entry is something to fix during the rewrite, not carry forward.'
id: 'project/design/architecture-v2/redesign-list'
scope: 'project'
type: 'design'
---

# Redesign List — Design

## Required reads

- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md

## Purpose

Catalog the design problems that surfaced in v1 and must not be reproduced in
v2. Each entry names the v1 pattern, the failure it causes, and the v2
correction. Reviewers consult this list during migration work; new code that
reintroduces any of these patterns is rejected.

## Inputs/Outputs

**Inputs:**

- the v1 codebase as it stands
- failure modes observed in operation (cache staleness, dual-transport bus,
  hook outbox, etc.)
- the architectural principles established in the v2 design docs

**Outputs:**

- the inventory of anti-patterns to fix during v2 rewrite
- the v2 corrections for each
- the rules reviewers apply to v2 PRs

## Invariants

- This is a living document. New anti-patterns get added when they surface.
- Every entry has: the v1 pattern, the failure it causes, the v2 correction.
- An entry is removed only when no v1 code still embodies the pattern and no
  recurrence is possible by construction in v2.
- Items here are NOT optional polish for v2. They are blockers — v2 alpha
  for a given service is not "alpha" if the service still embodies any item
  from this list.

## Primary flows

### Event/messaging anti-patterns

**1. Dual-transport event bus (LOCAL + CLUSTER).**
- *v1*: `EventBus.emit()` dispatches in-process for `EventVisibility.LOCAL`
  and via Redis Streams XADD for `EventVisibility.CLUSTER`. Same `emit()`
  signature, different delivery guarantees.
- *Failure*: Two paths with different durability, replay, and cross-process
  visibility properties under one API. Misclassifying an event as LOCAL
  silently drops cross-context delivery. Pool exhaustion is the symptom that
  forced the split; the split is the disease.
- *v2*: Single Redis transport for all events. `LocalSignal` exists as a
  separate Tokio `oneshot`/`broadcast` primitive for in-coroutine sync — it
  is not an event and may not be called one. Redis pool sizing handled by
  Tokio runtime efficiency, not by avoiding Redis.

**2. Cache fingerprint as change-detection.**
- *v1*: `DaemonCache._todos_fingerprint()` hashes selected DTO fields to
  decide whether to push a new snapshot. Fields not in the fingerprint
  silently fail to propagate.
- *Failure*: The reconcile-cache bug fixed in commit `bbf6e6342` — phase
  changes did not propagate because `lifecycle_phase` was missing from the
  fingerprint. Fundamentally fragile because fingerprint must be
  hand-maintained against the DTO shape.
- *v2*: No fingerprint-based change detection. Services emit events on
  every state change; subscribers (cache, TUI, browser bridge) react to
  events. Change detection is the event itself.

**3. Process-local mutation hooks.**
- *v1*: `TodosDb._on_mutation` callback fires only inside the process that
  did the write. Useless for cross-process notification.
- *Failure*: CLI/TUI writes don't notify the daemon. The architectural
  trigger for the v1 cache propagation bug.
- *v2*: No process-local hooks. Every mutation emits a Redis event. Any
  process that cares subscribes. Cross-process notification by construction.

### State machine anti-patterns

**4. Lifecycle phase computed only on reconcile.**
- *v1*: New todos are scaffolded with `lifecycle_phase = "draft"`. The
  state machine recomputes phase only when `telec todo reconcile` runs. In
  between, the persisted phase is stale.
- *Failure*: The DRAFT phase persists even after artifacts are present,
  because the state machine doesn't run on artifact-write. The user sees
  "draft" indefinitely.
- *v2*: State machine evaluates on every state-changing operation. There is
  no separate "reconcile" path — reconcile only exists as a debugging tool,
  not as part of normal flow. The persisted phase always matches what the
  machine would compute.

**5. Persisted state that the machine cannot reproduce.**
- *v1*: `DRAFT` phase exists in the enum and is persisted at scaffold time,
  but `_feature_phase` cannot return DRAFT for any todo with artifacts.
  Structurally unreachable yet stored.
- *Failure*: State that the machine can't justify is bookkeeping
  fiction. It exists only because of bootstrap order, not because of any
  real condition.
- *v2*: Initial state is the first phase the artifacts justify. No phase
  exists in storage that the state machine cannot derive. Constructors
  enforce this.

**6. Bureaucratic empty rows.**
- *v1*: `telec todo create <slug>` mints a row with no input artifact —
  "a draft todo skeleton with no input artifact." A todo without input has
  no purpose.
- *Failure*: Storage holds entities whose existence isn't justified by
  content. Operationally: the DRAFT phase only exists because such rows
  exist.
- *v2*: Constructors enforce that a `Todo` cannot be constructed without
  input. The act of capturing input is what creates the todo. No empty
  rows are possible.

### Service boundary anti-patterns

**7. Callers mutating service-owned storage directly.**
- *v1*: TUI's `action_reconcile` calls `reconcile_phase_state` in-process,
  writing `todos.db` directly. CLI handlers reach into `TodosDb` directly.
- *Failure*: Multiple call paths to mutation logic. No single point of
  enforcement. Bypasses any hooks or validation a service might do.
- *v2*: Services own their Postgres schemas. Other crates call the service's
  public function. Direct Postgres queries against another service's schema
  are forbidden (and effectively impossible because each crate's storage
  module is `pub(crate)`).

**8. HTTP between local Rust processes.**
- *Proposal smell*: "v1 daemon calls v2 workflow service via HTTP," "auth
  service exposes endpoints on a port," "TUI POSTs to the daemon to
  reconcile."
- *Failure*: Network/serialization overhead for what should be function
  calls. New failure modes (socket unreachable, port conflict). Reintroduces
  the daemon-as-gravity-well coupling.
- *v2*: HTTP exists only for the browser ↔ frontend ↔ daemon path
  (cross-language). All same-language local calls use crate dependencies
  (SDK). See transport-rules.

**9. Centralized DTO module mixing domain and transport.**
- *v1*: `teleclaude/api_models.py` holds DTOs used by both the API layer
  and domain code, conflating "what JSON looks like" with "what the entity
  is."
- *Failure*: Domain types get shaped by API/JSON concerns. Changing the
  API surface forces domain changes.
- *v2*: Domain models live in their service crate's `models.rs`. API DTOs
  live in `crates/telec-api/src/dtos/`. The HTTP layer translates domain
  models to DTOs at the boundary. Domain never knows it's being serialized.

### Storage anti-patterns

**10. Multiple SQLite databases scattered.**
- *v1*: `~/.teleclaude/teleclaude.db` (mixed concerns: sessions, ops,
  tokens, availability), `~/.teleclaude/mirrors.db` (transcripts),
  `{project}/.teleclaude/todos.db` (per project). Storage truth fragmented
  across files and concerns.
- *Failure*: No transactional coherence across files. Cross-cutting
  queries impossible. Backup story per-file. Per-file single-writer
  serialization bottleneck under multi-writer load.
- *v2*: Single local Postgres instance. Schema per service. MVCC handles
  the multi-writer reality. Per-project isolation via per-project schemas
  or `project_id` column within the service's schema.

**11. In-place schema upcycle ("upcycle on read").**
- *v1*: `_upcycle_blockers` rejects todos with `schema_version < 3`. The
  upgrade logic is in-place: read row, detect old schema, transform in
  memory. Fragile and easy to get wrong.
- *Failure*: A todo whose schema can't be upcycled is permanently blocked.
  Schema evolution is brittle.
- *v2*: Migrations via `sqlx::migrate!()` run once at service startup. If
  the database is behind, migration runs. If ahead, hard fail. No
  on-read transformation.

**12. Multi-step mutations split across writes.**
- *v1*: Logical operations stitched from multiple `INSERT`/`UPDATE`s
  without transactional boundaries.
- *Failure*: Partial states observable. Lock contention. Correctness
  risk.
- *v2*: Every logical mutation is one Postgres transaction. ACID by
  construction. If a mutation can't be expressed as one transaction, it's
  decomposed into independent steps with explicit event-driven coordination,
  not stitched.

### Storage tier anti-patterns

**13. Hook outbox DB.**
- *v1*: Hook receiver writes hook events to a SQLite outbox table for
  durability, then a worker drains to Redis.
- *Failure*: The outbox pattern is only justified when a DB write must be
  atomic with an external publish. Hooks have no DB write to bundle —
  they're just events. The outbox is a slower Redis queue with a foot-gun.
- *v2*: Hook receiver writes directly to Redis Streams via XADD. If Redis
  is down, the hook fails loudly — that's an operational signal, not a
  thing to paper over. No fallback storage.

**14. Defensive fallbacks for infrastructure being down.**
- *v1 pattern*: "Write to local file if Redis is unreachable," "cache locally
  if Postgres is down," "use in-memory queue if broker fails."
- *Failure*: Silent degradation. Hides outages that need fixing. Splits
  source of truth.
- *v2*: When Postgres is down, writes fail. When Redis is down, publishes
  fail. The failure is the signal. Infrastructure is part of the platform;
  its availability is an operational invariant, not something the
  application defends against.

### Daemon/runtime anti-patterns

**15. Daemon as gravity well.**
- *v1*: Daemon grew to own local bookkeeping, transport-driven business
  logic, cache invalidation, startup-critical side work, and authentication
  pressure that belongs at boundaries.
- *Failure*: Heavy daemon, slow restart, hard to reason about. Naming this
  in the v2 journey doc.
- *v2*: Daemon is narrow. It hosts the `agent_runtime` service in long-
  running form, the WebSocket bridge for browser delivery, and supervises
  worker subprocesses. Everything else lives in its own binary or its own
  service crate embedded by the binary that needs it.

**16. CLI commands routed through daemon API.**
- *v1*: Local CLI commands hit daemon-backed HTTP API paths in places where
  they should use local services directly. Violates local-first.
- *Failure*: CLI fails when daemon is down for local operations that should
  not depend on it. Reintroduces daemon as gravity well.
- *v2*: CLI binary embeds service crates directly. `telec todo list` calls
  `workflow::list_todos(...)` in-process, no daemon dependency, no HTTP.

**17. Daemon-as-WebSocket-relay for same-process subscribers.**
- *v1*: TUI connects to daemon's WebSocket. Daemon pushes cache notifications
  via WebSocket. The TUI could subscribe to the same source directly.
- *Failure*: Extra hop, extra protocol layer, daemon must stay up for TUI
  to get updates.
- *v2*: TUI subscribes to Redis directly. WebSocket exists only for browsers
  (which cannot subscribe to Redis themselves). The frontend custom server
  bridges browser-WebSocket to Redis-subscriber.

### Transcript/history anti-patterns

**18. Transcripts as a read model for multiple consumers.**
- *v1*: Mirrors and other consumers parse raw transcript JSON. Compensating
  mechanisms instead of clean architecture (named in journey doc).
- *Failure*: Brittle consumers tied to transcript format. Multiple
  parsers, multiple drift surfaces.
- *v2*: `session_ledger` service owns transcript ingestion and exposes
  typed queries. No other code parses transcript files. Mirrors as a
  compensating mechanism don't exist.

### Identity/auth anti-patterns

**19. Multiple accreted auth paths.**
- *v1*: `x-session-token`, `x-caller-session-id` + `x-tmux-session`
  cross-check, `x-telec-email`. Three paths, each pragmatic in isolation.
- *Failure*: Resolution logic spread across middleware layers. Hard to
  reason about "who is this caller."
- *v2*: `identity` crate is the single resolution authority. Every
  transport adapter (CLI, HTTP, hook receiver) converts its evidence into a
  `Principal` via the crate. Resolution logic is centralized; transports
  adapt their inputs to a uniform interface.

### Hooks/integration anti-patterns

**20. Hooks doing identity resolution and event emission inline.**
- *v1*: Hook receiver subprocess does a lot — resolves identity, validates
  context, emits events, sometimes does business logic.
- *Failure*: Hook receivers become large and bug-prone. Business logic in a
  short-lived subprocess invocation.
- *v2*: Hook receivers are tiny: parse the typed payload, emit a Redis
  event with the relevant fields, exit. All downstream work happens in
  long-running services that subscribe.

**21. Per-project host-level watchers.**
- *v1*: Per-project watcher services accumulated as host-level operational
  debt (named in journey doc).
- *Failure*: Many services to manage, install, debug. Machine-level
  instability.
- *v2*: One watcher per host at most, or none if events suffice. Watchers
  publish to Redis, services subscribe.

### CLI/TUI anti-patterns

**22. 50+ flat top-level CLI subcommands.**
- *v1*: `telec ...` has dozens of subcommands at the top level, with
  inconsistent verb-noun shape.
- *Failure*: Hard to discover. Hard to remember. New commands accrete
  without organization.
- *v2*: Hierarchical command structure with consistent verb-noun shape.
  `telec todo list`, `telec todo create`, `telec sessions list`. Commands
  group under nouns.

**23. TUI re-implements business logic.**
- *v1*: TUI's `action_reconcile` calls `reconcile_phase_state` in-process,
  mutating storage directly.
- *Failure*: TUI contains logic that should live in services. Multiple
  call paths to the same operation. Reasoning about correctness requires
  reading the TUI code.
- *v2*: TUI is pure view + dispatch. TUI calls service crate functions the
  same way the CLI does. Zero business logic in TUI code.

### Tooling/git anti-patterns

**24. Git wrapper at `~/.teleclaude/bin/git` blocking destructive ops.**
- *v1*: Wrapper script enforces "no `git stash`, no `git reset --hard`" by
  shadowing `git` on PATH. Requires PATH manipulation in every shell.
- *Failure*: Clever but brittle. PATH ordering bugs. Doesn't enforce when
  invoked from automation that bypasses the shell.
- *v2*: Don't wrap git. Encode the same rules in a pre-commit hook
  installed once. CI enforces the same rules. Discipline lives where it can
  actually be enforced, not in a shell wrapper.

### Process/operations anti-patterns

**25. Mixed startup/shutdown boundaries.**
- *v1*: Many subsystems start, stop, and fail together. Daemon, API,
  watchers, projection work, optional subsystems all coupled.
- *Failure*: Restart pain. One failure cascades.
- *v2*: Each service is independently restartable. Binaries have explicit
  lifecycles. Daemon hosts what genuinely needs supervision; other
  binaries run when called.

### Path/install anti-patterns

**26. Operational state stored as files.**
- *v1*: SQLite databases (`teleclaude.db`, `mirrors.db`, `events.db`)
  plus JSON state files (`state/session_map.json`, `state/runtime-settings.json`,
  `state/cron_state.json`, etc.) all under `~/.teleclaude/`. State and
  config conflated in the same tree.
- *Failure*: Concurrent-writer contention on SQLite. No transactional
  coherence across files. Fragmented storage. Manual coordination via
  lock files (`git-main.lock`). Backup conflates ephemeral state with
  durable config.
- *v2*: State lives in Postgres (per-service schemas). Coordination via
  Postgres advisory locks or Redis SET NX. Lock files and PID files
  retire. The `~/.teleclaude/` home dir stays — but only for
  authored/installed content (config, secrets, deployed commands, shell
  scripts, sandbox profiles, per-machine preferences). The directory
  itself is the same shape v1 has; the contents shrink dramatically as
  state moves out.

**27. Python tooling workarounds (uv cwd mangling, venv re-exec) baked
into path resolution.**
- *v1*: `TELEC_INVOCATION_CWD` env var exists to recover actual cwd
  after `uv run --directory` changes process cwd. Hook receiver does a
  `.venv` resolution dance and re-execs under the project's Python venv.
  ~half of v1's path-resolution code is Python tooling workarounds.
- *Failure*: Code paid as architectural tax for the host runtime's
  problems, not for real domain requirements.
- *v2*: Single-binary Rust executables have no venv and no uv. The
  workaround code simply doesn't exist. `std::env::current_dir()` is
  authoritative; binaries are self-contained.

## Failure modes

The meta-failure modes that produced this list in the first place:

- **Porting v1 patterns wholesale.** Treating v2 as a "rewrite in
  Rust" instead of "redesign that drops the anti-patterns we know."
  Each entry above is a pattern that must NOT be reproduced.
- **Pattern matching to v1 because it exists.** "v1 does X so v2 should
  do X" without asking "is X right, or is X what v1 happened to do?"
  The change-axis heuristic (transport-rules.md) is the discipline that
  catches this.
- **Silent re-introduction.** A pattern from the list gets
  re-introduced because the agent didn't read this doc. Reviewers must
  reference this list during PR review; new code reproducing any entry
  is rejected.
- **Adding to the list without acting on it.** Identifying an
  anti-pattern is not the same as fixing it. Each entry must have a v2
  correction; entries without a correction are incomplete.

## See Also

- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md
- docs/project/design/architecture-v2/event-bus-transports.md
- docs/project/design/architecture-v2/journey.md
