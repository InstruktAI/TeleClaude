---
id: project/spec/domain/workflow
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by:
  - v2-workflow-cutover
  - removal-snippet-frontmatter-sync
  - roadmap-trash-reveal-ui
  - v2-workflow-cli-refinement-commands
  - v2-workflow-creation-cleanup
  - v1-workflow-creation-hardening
description: Workflow bounded context — todos, roadmap entries, preparation artifacts,
  lifecycle state machines. The system that organizes what gets built.
---

# Workflow Domain Spec — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md
- @docs/project/spec/domain/event-catalog.md

## What it is

The `workflow` bounded context owns the platform's todos, roadmap, and the state machines that drive a todo from idea to delivered. It owns the preparation artifacts (PRD, a thin architecture index/log, implementation plan, etc.), the stage and phase progressions per todo, the dependency graph between todos, and the bookkeeping that makes the work visible. Architectural design is authored directly into domain/design doc snippets; the `architecture` artifact only logs which snippets a todo touched.

This context does NOT own: the live agent sessions doing the work (`agent_runtime`), the transcript history of those sessions (`session_ledger`), the doc snippet content (`knowledge`), or the integration that delivers outbound notifications (`integration`). Workflow is local-first and authoritative for the per-project todo store; it operates without daemon dependency for its core operations.

## Canonical fields

### Ubiquitous language

**Todo**
: A unit of work flowing through the lifecycle. Has a slug, a kind, a stage, current phase within stage, a set of artifacts. The atomic deliverable unit of workflow.

**Slug**
: A kebab-case name for a todo, stable across that todo's lifetime except via the atomic `telec todo rename` operation — the only sanctioned slug mutation (see the Todo-aggregate invariant and UC-WFL-13). It is the **active alias**, not the durable row identity: a roadmap entry has its own durable row identity (v1: `roadmap.id`), and `slug` is unique only among **live** entries (`active`/`icebox` and their derived `pending`/`in_progress` display states). Retained non-live rows — `delivered` (history) and `removed` (within the retention window) — may share a slug with a fresh live entry. Resolving a slug to "the todo" therefore means "the live entry for this slug"; history/removed rows are addressed by durable row identity.

**Removal tombstone**
: Durable, row-id-keyed metadata captured on the roadmap row at soft-remove time, alongside `removed_at`. It holds `prev_status` — the status the entry held immediately before removal (`active` or `icebox`) — and `removed_deps` — a snapshot of the entry's own outgoing `after` edges as they were at removal. Both exist only so reactivation can restore the entry's own footprint exactly. The snapshot is necessary because `roadmap_deps` is slug-keyed with no row identity: the live outgoing edges MUST be scrubbed at soft-remove (or a same-slug recreate would inherit/collide with them), so they can only survive for reactivation by being parked here. Legacy rows removed before this metadata existed have neither; reactivation falls back to `prev_status=icebox` and no outgoing-edge restore.

**Kind**
: Categorical label for the type of work: `feature`, `bug`, `refactor`, `migration`, `prepped`. Determines which lifecycle gates apply (e.g., `bug` skips the demo phase in finalize; `prepped` skips prepare).

**Stage** (per glossary)
: Top-level lifecycle band: `draft`, `prepare`, `work`, `integrate`, `delivered`. Each stage is a coherent body of work with its own state machine inside.

**Phase** (per glossary)
: Sub-state within a stage. Examples for `prepare` stage: `intake`, `prd_drafting`, `prd_human_approval`, `architecture_drafting`, `architecture_review`, `plan_drafting`, `plan_review`, `drift_analysis`, `prepared`.

**Artifact** (workflow artifact — per glossary)
: A document produced during a todo's lifecycle. Canonical kinds: `input`, `prd`, `architecture` (thin index/log of touched doc snippets), `implementation-plan`, `bug`, `quality-checklist`, `design-spec`, `deferrals`, `requirements-review-findings`, `architecture-review-findings`, `plan-review-findings`, `review-findings`. Stored as TEXT in `workflow.artifacts`. (`test-specs` and `spec-review-findings` are retired legacy kinds, accepted only for reading/removing pre-cutover todos.)

**Roadmap**
: The ordered list of todos with their dependency edges, groupings, and statuses. The public face of "what's being worked on and what's next."

**Roadmap entry**
: One row in the roadmap, addressed by its own durable row identity (v1: `roadmap.id`). Carries: slug (the active alias), the **persisted** `status` (`active` | `icebox` | `delivered` | `removed`), `removed_at` (tombstone timestamp, set only when `status=removed`), `prev_status` and `removed_deps` (the Removal tombstone — pre-removal status and the outgoing-`after`-edge snapshot, set only when `status=removed`), `after` (live dependency slugs), `before` (insertion anchor), optional `group` and `description`. Persisted `status` is distinct from the roadmap **display state**: the roadmap view derives `pending` / `ready` / `in_progress` from a live (`active`) entry plus its lifecycle phase, while `delivered`/`icebox` surface directly and `removed` is hidden from the default view (visible only via the recovery surface). The soft-delete invariants below operate on the persisted vocabulary.

**Dependency**
: An `after` relationship between roadmap entries. Todo A is `after: [B, C]` means A cannot start until B and C are `delivered`.

**Icebox**
: Frozen-but-recoverable state for roadmap entries that aren't being actively pursued. Lives at `todos/_icebox/`. Unfreeze restores to the active roadmap.

**Removed (soft-deleted)**
: A roadmap entry that an operator/agent explicitly removed. The entry is marked `status=removed` with a `removed_at` tombstone timestamp; the row and the Todo's state, artifacts, and full artifact-version history are **retained** (not cascade-deleted). A removed entry is invisible to every default read path. It is the todo-store analogue of the closed-session soft-delete (`sessions.closed_at` + `lifecycle_status='closed'`), and follows that mechanism deliberately rather than introducing a divergent one.

**Retention purge**
: Routine maintenance hard-purges removed entries whose `removed_at` is older than a fixed retention window — the same window the platform applies to closed sessions. The purge is a **hard `DELETE` of the retained roadmap row addressed by its durable row id**, and nothing else: the `ON DELETE CASCADE` FK from `todo_state`/`todo_artifacts` removes state, artifacts, and artifact versions. The purge performs **zero slug-keyed operations** — no `roadmap_deps` scrub (not even a defensive one) and no worktree/branch/workspace cleanup — because every slug-keyed teardown already ran at soft-remove, and by purge time a same-slug live todo may exist; a slug-keyed delete here would destroy that live todo's dependency edges or working resources. The full removal cascade is preserved, simply split by key-safety: all slug-keyed teardown at soft-remove (when the slug unambiguously names the removed entry), physical row + FK cascade at purge (row-id-addressed, slug-agnostic). It is NOT a reuse of the slug-keyed remove helpers — those resolve through active-row resolvers that, by design, no longer see `removed` rows; the purge addresses the roadmap row by id. Each sweep also self-heals legacy/partial rows (mirrors the closed-session sweep's normalization step).

**Reactivation**
: Restoring a removed-but-not-yet-purged entry. The primitive's input is a **durable roadmap row id**, never a bare slug: repeated remove → recreate-same-slug → remove cycles can leave several `removed` rows sharing one slug, so the slug does not uniquely identify a reactivation target. The primitive restores the one `removed` row named by that row id — clearing `removed_at`, restoring `prev_status` (`icebox` only as the legacy-row fallback), replaying the `removed_deps` snapshot as the entry's outgoing `after` edges, and recovering the retained state, artifacts, and versions; the entry's own footprint is then indistinguishable from never-removed. Inbound edges other todos previously held on the slug are NOT resurrected (they were scrubbed at remove time and belong to those other todos). Reactivation is **fail-closed**: it refuses and changes nothing if a live (`active`/`icebox`) entry already exists for that row's slug, or if the row id does not name a `removed` row. The downstream recovery UI enumerates removed rows and supplies the row id; this context exposes only the row-id-addressed primitive.

**State machine**
: The engine that advances a todo's phase based on artifact production, review verdicts, and orchestrator decisions. Per-stage: prepare state machine, work state machine, integrate state machine.

**Verdict**
: A reviewer's output on a workflow artifact: `approve`, `needs_work`, `needs_decision`. Drives state machine transitions.

**Operation**
: A long-running task tied to a todo (e.g., a worker session doing build). Tracked as `agent_runtime.operations` from workflow's perspective via the `operation.completed` event.

**Delivery commit**
: The git commit SHA on `main` that materialized the todo's outcome. Non-empty when stage is `delivered`. The audit trail anchor.

### Aggregates

#### Todo (aggregate)

- **Root:** `Todo`
- **Contains:** a durable row identity (the persistent key); the Slug as its active alias; current StageState (which stage, which phase, in_progress vs awaiting); the Artifact collection (each artifact has version history); dependency edges (`after` slugs); kind; optional grouping; optional description.
- **Invariants:**
  - A todo has exactly one current `(stage, phase)` at any moment.
  - Stage progression is strictly forward: `draft → prepare → work → integrate → delivered`. No backwards transitions; recovery from failure happens within the current stage's machine.
  - An artifact's version history is append-only; old versions are referenced by digest.
  - A todo's `kind` is fixed at creation; changing kind requires deletion + recreation.
  - A todo cannot reach `delivered` stage without a non-empty `delivery_commit` and a successful integrate-state-machine terminal state.
  - Dependency cycles are forbidden — the dependency graph MUST be a DAG.
  - A todo's slug is immutable across its lifetime EXCEPT via the atomic
    rename operation (`telec todo rename`), which is the only sanctioned slug
    mutation. Rename re-keys the slug across its atomic unit as a single
    all-or-nothing operation (see UC-WFL-13): the structured todos.db
    surfaces — `roadmap.slug`/`group_slug`/`children`, the denormalized
    `todo_state.slug` column and only **typed structured** slug references in
    the state blob (e.g. breakdown child refs), `todo_artifacts.slug` +
    version history, and `roadmap_deps.slug`/`depends_on` both directions —
    the snippet `delivered_by` frontmatter, and the local
    worktree/branch/workspace. Arbitrary prose / event-detail / free-text in
    the state blob is NOT rewritten (the PRD Won't scope). It targets only the
    single **live** entry for the old slug; retained `delivered`/`removed`
    historical rows keep their original slug because they are addressed by
    durable row identity, not by the active alias. The remote branch and
    daemon-DB references are reconciled outside the atomic unit (see
    UC-WFL-13). Rename is refused while in-flight work is bound to the slug,
    and refused if any non-removed entry already holds the new slug (only
    soft-`removed` retained slugs are collision-free rename targets,
    consistent with the slug-reuse rule).
  - At most one **live** entry (`active`/`icebox`) exists per slug at any moment; `delivered` and `removed` retained rows for the same slug are permitted as additional historical rows, distinguished by durable row identity.
  - **Creation requires substantive content.** A creation request that supplies no content is refused at the service boundary — no roadmap row, no `todo_state` row, no `input` artifact row, and no artifact-version row is written, and no `workflow.todo.created` event is emitted. This invariant exists because the previous empty-skeleton path produced `(stage=draft, phase=draft, state=in_progress)` rows in which nothing was actually in progress, with no input to act on; the only way to keep the persisted state truthful is to refuse the operation. Substantive-create vs. silent-create is orthogonal to this requirement: both modes require content; they differ only in pickup-dispatch semantics (see the `workflow.todo.created` payload). **Pre-cutover legacy rows** that already persist the misleading skeleton shape are addressed operationally by UC-WFL-2b (`telec todo doctor --skeletons`), which surfaces them by default (read-only report) and can soft-remove them via opt-in `--migrate` through the standard remove path (recoverable within the retention window). A destructive one-shot SQL backfill is forbidden.
- **Identifier:** durable row identity. `slug` is the active alias used to resolve the single live entry; it is not globally unique across retained history.
- **Lifecycle:** Created via `telec todo create <slug> <content>` (substantive — content required at creation; an empty-content invocation is refused and writes nothing) or `telec todo split` (child of a container). `telec todo dump` survives one transition window as a warning compatibility alias for `telec todo create` and produces the same substantive-create outcome. Advances through stages via the per-stage state machine. Reaches `delivered` via integration. Frozen aggregates move to icebox.

#### Roadmap (aggregate)

- **Root:** `Roadmap` (per-project; one roadmap per `.teleclaude/todos.db`)
- **Contains:** ordered list of `RoadmapEntry` values, each referencing a Todo by slug; the dependency graph; optional group labels.
- **Invariants:**
  - Every roadmap entry references exactly one todo (1:1), keyed by durable row identity. At most one **live** entry exists per slug; retained `delivered`/`removed` rows may share that slug as additional historical rows.
  - The dependency graph (`after` edges across all entries) is a DAG.
  - Ordering within the roadmap is explicit and operator-controlled (via `move`, `add --before`, `add --after`); the system does not auto-reorder.
  - Icebox entries do NOT participate in the active dependency graph; unfreezing restores them.
  - Delivered entries remain in the roadmap (visible via `--include-delivered`) for history.
  - **Removal is soft and retained.** `telec todo remove` / `telec roadmap remove` mark the entry `status=removed`, `removed_at=now()`, and write the removal tombstone (`prev_status` + `removed_deps`). They do NOT delete the entry's Todo state, artifacts, or artifact-version history — survival for reactivation is the point. The roadmap row itself is also retained (not physically deleted) during the retention window: the FK from `todo_state`/`todo_artifacts` to the roadmap row is `ON DELETE CASCADE`, so physically deleting the row at remove-time would destroy the very history the soft-delete exists to keep. The exception to "retain everything" is **all slug-keyed teardown**, which runs at soft-remove while the slug unambiguously names this entry: both directions of the entry's live `roadmap_deps` rows are deleted (outgoing snapshotted into `removed_deps` first; inbound discarded), and the slug's git worktree, local + remote branch, and workspace directory are cleaned up. None of this is deferred to purge: by purge time a same-slug live todo may exist, and any slug-keyed operation would destroy that live todo's edges or working resources. The durable record (row + state + artifacts + versions + tombstone) is what is retained.
  - **Removed entries are invisible to every default read path.** Every slug→row resolver, the roadmap-assembly read, cache-backed default reads, AND slug-enumeration paths (notably `list_slugs` over `todo_state` and its service/protocol wrappers) exclude `status=removed` by default — exactly as non-included delivered/icebox entries are excluded. Because soft-remove retains `todo_state` rows, any state-derived enumeration that does not gate through live roadmap status would leak removed todos; the gating contract is therefore exhaustive and includes `list_slugs`. A removed entry does not participate in the active dependency graph. **Two sanctioned reveal paths exist alongside the default-hide invariant**, both strictly opt-in: the durable row-id-addressed reactivation query (used by the recovery primitive — UC-WFL-12), and the operator-facing recovery surface (UC-WFL-14 / UC-WFL-15) — `telec roadmap list --include-removed` / `--removed-only`, `telec todo show <slug>` with the opt-in reveal flag, and the TUI trash-toggle. **Reveal paths split by surface — CLI reaches the workflow DB via the existing resolvers (locally for `roadmap list`, via the daemon REST API for `todo show`); the daemon cache contract is TUI-only:** the CLI reveal consumers each follow their existing topology. `telec roadmap list --include-removed` / `--removed-only` invokes `assemble_roadmap_from_db` locally with the new `include_removed` / `removed_only` keyword args. `telec todo show --include-removed` continues to call the daemon REST API (`GET /todos/{slug}/show?include_removed=true` via the existing `tool_api_request` client); the new include-removed resolver lives on the API route and assembles the row-id-backed show payload server-side. Neither CLI command consults the daemon roadmap cache snapshot. The daemon roadmap cache is scoped to the high-frequency TUI roadmap pane: it stores one snapshot per project that holds the full persisted roadmap including `removed` rows (preserving the cache-system "Single Snapshot Per Scope" invariant); every default cache accessor applies a filter at read time that excludes `removed`, so the TUI's default sections continue to see exactly what the default resolvers expose; the TUI Trashed section reads the SAME cache snapshot with the filter relaxed via a per-call opt-in flag. The filter — never the snapshot — is what changes between default and reveal paths on the TUI side, and the cache shape itself never widens to a second-snapshot variant. Orchestration slug enumeration, integration finalize, and work dispatch always use the default-filtered path. Snippet validation is the explicit exception named in the adjacent invariant below — it reads the roadmap status map directly (treating `removed` as known-but-not-delivered) rather than through the default-hidden filter, so retained removed slugs don't trigger `snippet_delivered_by_unknown_slug` during the recovery window.
  - **Removed entries do not collide with slug reuse.** The active-slug uniqueness constraint covers only `status IN ('active','icebox')`; `removed` sits outside that predicate, so a freshly created entry may reuse a slug while a removed-and-retained twin still exists. No uniqueness-index change is required. Crucially, a removed entry holds NO live slug-keyed `roadmap_deps` rows (they were scrubbed at soft-remove, outgoing parked in the row-id-keyed `removed_deps` tombstone), so a same-slug recreate starts with a clean dependency set and cannot inherit the removed entry's edges. Reactivation (which restores `removed_deps`) is itself fail-closed against a live same-slug twin, so the two can never both hold live edges for the slug.
  - **Retention finalization is automatic and row-id-only.** Routine maintenance hard-purges entries with `removed_at` older than the fixed retention window (the same window applied to closed sessions) by hard-`DELETE`ing the retained roadmap row **by durable row id**; the `ON DELETE CASCADE` FK removes state/artifacts/versions. The purge performs **zero slug-keyed operations** — no `roadmap_deps` scrub (not even defensively) and no worktree/branch/workspace cleanup — because all slug-keyed teardown ran at soft-remove and a same-slug live todo may exist by purge time; a slug-keyed op here would destroy that live todo's edges or resources. The full removal cascade is preserved, split across the two phases: all slug-keyed teardown at soft-remove, physical row + FK cascade at purge. It does not call the slug-keyed remove helpers. Each sweep self-heals legacy/partial rows. This finalizes an already-explicit operator removal after a recovery grace period; it is not blind pruning of live durable data.
  - **Retention purge is atomic with documentation reconciliation.** A retained roadmap row may be named as a `delivered_by` slug on `target` / `mixed` doc snippets. The retention sweep couples the per-row hard-`DELETE` with snippet frontmatter reconciliation so that no snippet ever points at a slug whose roadmap row no longer exists. Reconciliation reuses the canonical frontmatter primitives (the same parse/render engine the post-delivery flip uses) and applies a row-keyed rule: (a) **multi-slug** `delivered_by` — the purged slug is dropped from the list; the snippet keeps its `status: target` / `mixed`; the row is then hard-DELETEd in the same sweep; (b) **sole-slug** `delivered_by` (the purged slug is the only entry) — the snippet is NOT auto-mutated and the hard-DELETE for that one row is SKIPPED on this sweep; the sweep emits a structured WARNING naming the snippet path and the orphaning slug, then continues with the remaining expired rows. The sole-slug case is deliberate: silently flipping the snippet to `status: actual` would assert delivery of work that was never delivered, so the sweep stalls the purge for that one row until a human edits the snippet (flip to `actual`, drop `delivered_by`, or update body). The ordering guarantee for the multi-slug case is **snippet write completes before the row hard-DELETE**; the inverse ordering is forbidden because it leaves snippets transiently pointing at a non-existent slug. Concurrent `telec sync` therefore never observes a snippet whose `delivered_by` names a vanished roadmap row.
  - **Soft-removed slugs remain known to the doc snippet validator during the trash window.** Snippet validation queries the roadmap status map; an entry whose status is `removed` is treated as a known slug (validation does not raise `snippet_delivered_by_unknown_slug` against it) but is NOT treated as `delivered` for the unflipped-drift check. This keeps `telec sync` operational across soft-remove / reactivate cycles without prematurely retiring snippet targets, while preserving the existing safety on genuinely unknown slugs and on delivered-but-unflipped drift.
  - **Reactivation is fail-closed.** The primitive takes a **durable roadmap row id** (not a slug — repeated remove/recreate can leave multiple `removed` rows per slug). It fully recovers that row's own footprint (roadmap row + state + artifacts + versions) to the persisted `prev_status` (legacy-row fallback `icebox`) and replays `removed_deps` as the entry's outgoing `after` edges — making the entry indistinguishable from never-removed at its own aggregate level. Inbound edges other todos held on the slug are NOT resurrected: they were scrubbed at remove time and are those other todos' state (a dependent re-declares if still needed). It refuses and mutates nothing if a live (`active`/`icebox`) entry exists for that row's slug, or if the id does not name a `removed` row — it never overwrites, merges, or silently resurrects. Targeted/rename restore is out of scope for this context (it belongs to the recovery UI, which supplies the row id).
- **Identifier:** the per-project roadmap is unique per project; no separate identifier.
- **Lifecycle:** Created when the project is initialized. Mutated by `telec roadmap add/remove/move/deps/freeze/unfreeze/deliver`. `remove` is soft + retained (above), finalized by the maintenance retention purge or reversed by reactivation. Persists for the project's lifetime.

#### Artifact (aggregate, lives inside Todo)

- **Root:** `Artifact`
- **Contains:** kind (one of the canonical artifact kinds); content (TEXT); version history (digest + timestamp per version); current version pointer. Bound to its owning roadmap row by that row's durable identity (v1: the `roadmap.id` foreign key on `todo_artifacts`), not by slug.
- **Invariants:**
  - Artifact content is append-only at the version level; replacing content creates a new version, never mutates an existing one.
  - Each artifact kind is unique per **roadmap row** (one `prd` per row, one `implementation-plan` per row, etc.) — keyed by durable row identity, so a retained `removed` row and a fresh same-slug live row each hold their own independent artifact set.
  - Removing an artifact (`telec todo artifacts remove`) deletes the artifact + its full version history.
  - The current version pointer is the most-recently-written version.
- **Identifier:** `(durable roadmap row identity, artifact_kind)`. Slug is only the alias used to resolve the live row; it is never the artifact's durable key (same-slug retained/live rows would otherwise collide).
- **Lifecycle:** Created by `telec todo artifacts write` or as a side effect of state-machine transitions. Versioned on every write. Removed by explicit `telec todo artifacts remove`.

### Domain events emitted

#### `workflow.todo.created`

- **Producer:** `workflow`
- **Emitted when:** a new todo is added to the roadmap (via `create`, the
  `dump` compatibility alias, `split`, `bugs report`, `bugs create`). Always
  emitted on successful creation regardless of `creation_mode` — silent mode
  suppresses pickup dispatch, not the state-change event.
- **Payload:** preserves the existing v2 Rust contract — `todo_id` (durable
  row identity), `slug`, `project_id`, `lifecycle_phase` (always `draft`
  initially), `kind`, `created_at`, `created_by_principal` — and adds two
  new fields owned by this delivery: `creation_mode` (`pickup` | `silent`)
  and `pickup_requested` (boolean). The v1 daemon bridge derives the
  consumer-facing `project_path` from `project_id` via its existing
  `project_id → project_path` map (the bridge is payload-agnostic and reads
  the whole envelope; see `teleclaude/transport/workflow_bridge.py`).
  Existing v2 Rust event consumers continue to see every prior field; the
  contract is strict-additive.
- **Visibility:** CLUSTER
- **Known consumers:** `integration` (subscription notifications for
  "todo created"), audit log consumers, autonomous pickup consumers (the
  prepare / work dispatch routers — they react ONLY when
  `pickup_requested = true`; silent-mode events update cache and audit but
  trigger no dispatch).
- **Idempotency key:** `slug`.
- **Posture:** `commit-then-emit`.
- **Why pickup is a payload field, not a separate event:** silent creation
  must remain a true state-change event so cache invalidation, bridge
  refresh, and audit consumers observe the new aggregate; hiding the event
  to suppress pickup would weaken all three consumer classes equally to
  serve only the dispatch class. Encoding pickup intent in the payload
  preserves the state-change contract and lets autonomous dispatch consumers
  gate themselves explicitly.

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

#### `workflow.todo.renamed`

- **Producer:** `workflow`
- **Emitted when:** the atomic rename operation commits the todo slug change from `old_slug` to `new_slug`.
- **Payload:** `old_slug`, `new_slug`, `renamed_at`, `renamed_by_principal`, `surfaces_moved`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` and `telec-tui` slug-keyed caches, `integration` notification dispatch, audit consumers.
- **Idempotency key:** `(old_slug, new_slug, renamed_at)`.
- **Posture:** `commit-then-emit`; terminal/audit daemon reference reconciliation is post-commit best-effort, not an atomic rollback leg.

#### `workflow.roadmap.entry_moved`

- **Producer:** `workflow`
- **Emitted when:** an operator changes the order of entries (via `telec roadmap move`), changes a dependency edge (`deps`), or freezes/unfreezes an entry.
- **Payload:** `slug`, `change_type` (`reordered` | `dependency_changed` | `frozen` | `unfrozen` | `delivered`), `details`, `moved_at`, `moved_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (roadmap view refresh), `telec-tui` (cache invalidation).
- **Idempotency key:** `(slug, change_type, moved_at)`.
- **Posture:** `commit-then-emit`.

#### `workflow.todo.renamed`

- **Producer:** `workflow`
- **Emitted when:** `telec todo rename` commits the slug re-key (after the
  todos.db transaction commits — the rename's linearization point).
- **Payload:** `old_slug`, `new_slug`, `renamed_at`, `renamed_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers** and the route by which each receives the
  `old_slug → new_slug` pair:
  - **v1 daemon bridge** (`teleclaude/transport/workflow_bridge.py`) —
    receives the full payload dict (the bridge is payload-agnostic and
    forwards the whole envelope to its caller-supplied dispatcher). The
    rename dispatcher reads `payload['old_slug']` and `payload['new_slug']`
    and performs a slug-keyed re-key on `DaemonCache`: drop the `old_slug`
    cache entry, force-refetch `new_slug`. This requires the rename's
    dispatcher to be payload-aware (a strict extension of today's generic
    "todos_updated" invalidation — that generic fallback is preserved for
    every other workflow event).
  - **`telec-tui`** — reads the daemon roadmap cache snapshot; receives the
    re-key as the cache-invalidation side effect above. The TUI does not
    subscribe to the bus directly.
  - **`frontend`** — receives the rename via the daemon's WebSocket push
    layer, which already exists for `todos_updated` and is extended here
    with a typed `todo_renamed` push carrying the `(old_slug, new_slug)`
    pair so the frontend can re-key in place rather than refetch the entire
    roadmap.
  - **`integration`** — slug-keyed subscription bookkeeping. Receives the
    pair from the bus subscriber the same way the daemon does.
  A rename changes the aggregate's active alias; consumers that cache by
  slug cannot learn the re-key from a generic `workflow.todo.updated`
  (which carries only the post-rename slug), so a dedicated event carrying
  the `(old_slug, new_slug)` pair is required rather than reusing
  `updated`. Exhaustive consumer-wiring breadth (including the per-consumer
  fallback when a payload-aware dispatcher has not yet been wired) is an
  implementation-plan concern; the durable contract is the `(old_slug,
  new_slug)` pair carried end-to-end through bridge → dispatcher → cache /
  WebSocket / integration subscriber.
- **Idempotency key:** `(old_slug, new_slug, renamed_at)`.
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

#### UC-WFL-1: Create a substantive todo with content

```
Given an operator (or agent) wants to register substantive work
When they run `telec todo create my-feature "<substantive content>" --kind feature --after upstream-slug`
Then workflow validates the slug is unique among live entries and kebab-case
And validates the content is non-empty
And validates `upstream-slug` exists in the roadmap
And creates the Todo aggregate, RoadmapEntry, input Artifact, and initial artifact-version in one transaction
And emits workflow.todo.created with creation_mode=pickup and pickup_requested=true
And autonomous pickup consumers dispatch the relevant prepare/work entry
```

#### UC-WFL-2: Empty-content creation is refused

```
Given an operator (or agent) runs `telec todo create my-feature` with no content
When the workflow service receives the request
Then it rejects with a typed empty-input error
And writes no roadmap row, no todo_state row, no artifact row, and no artifact-version row
And emits no workflow.todo.created event
And no autonomous pickup is triggered
```

#### UC-WFL-2a: `telec todo dump` compatibility alias

```
Given the transition compatibility alias is enabled
When the operator runs `telec todo dump my-feature "<content>"`
Then the CLI emits a deprecation warning naming `telec todo create` as the replacement
And forwards to the substantive-create path with the same arguments
And the resulting persisted state is indistinguishable from `telec todo create my-feature "<content>"`
And exactly one workflow.todo.created event is emitted (no double-dispatch)
```

#### UC-WFL-2b: Surface (and optionally migrate) pre-cutover v1 skeleton rows

```
Given the operator wants to discover legacy v1 skeleton todos — rows produced by the removed empty-skeleton create path, persisted with lifecycle_phase=draft and `state=in_progress` but no `input` artifact
When the operator runs `telec todo doctor --skeletons`
Then workflow scans todo_state rows where lifecycle_phase IS draft AND no `input` artifact exists in todo_artifacts
And prints a structured operator report listing each detected slug with its kind, created_at, and the absence of input
And no mutation occurs (default behavior is read-only — surfacing only)
And exit code 0 when no skeletons are found; non-zero with the report when any are found
```

```
Given the operator has reviewed the surfacing report and wants to retire the detected skeletons
When the operator runs `telec todo doctor --skeletons --migrate`
Then workflow soft-removes each detected skeleton via the standard remove path (status=removed, removed_at, removal tombstone, slug-keyed teardown — UC-WFL-10), one row at a time
And each removal emits the same events the remove path normally emits
And each removed entry remains recoverable via reactivation during the retention window
And the operator report lists the removed slugs and their durable row ids for audit
And exit code 0 when all detected skeletons were soft-removed successfully
```

The migration mechanism deliberately reuses the soft-remove primitive
(UC-WFL-10) rather than introducing a destructive backfill: legacy
skeletons are an operator-visible defect, not data the operator chose; soft
remove preserves the row for the retention window so any genuinely-intended
skeleton can be reactivated. A separate one-shot SQL migration is rejected
because it would bypass the slug-keyed teardown invariants and prevent
reactivation.

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
Given a todo is awaiting human approval at a gate phase (prd, architecture, plan)
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

#### UC-WFL-10: Soft-remove a todo

```
Given an operator or agent runs `telec todo remove <slug>` (or `telec roadmap remove <slug>`)
Then workflow marks the roadmap entry status=removed and removed_at=now()
And captures prev_status and snapshots the entry's outgoing after-edges into the removal tombstone (removed_deps)
And retains the Todo state, all artifacts, and all artifact versions (no cascade delete)
And performs ALL slug-keyed teardown now, while the slug unambiguously names this entry: deletes from the live roadmap_deps table BOTH the entry's outgoing edges (slug == removed_slug) and inbound edges (depends_on == removed_slug); and removes the slug's git worktree, local + remote branch, and workspace directory
And the entry disappears from every default CLI/TUI/cache read
And a new todo may immediately be created reusing the same slug with no inherited dependencies, no worktree/branch clash, and no collision
```

#### UC-WFL-11: Retention purge finalizes an expired removal

```
Given a roadmap entry has status=removed with removed_at older than the retention window
When the routine maintenance sweep runs
Then workflow hard-DELETEs the retained roadmap row by its durable row id
And the ON DELETE CASCADE FK removes state, artifacts, and artifact versions
And the purge performs ZERO slug-keyed operations — no worktree/branch/workspace cleanup and no roadmap_deps scrub — because all slug-keyed teardown already ran at soft-remove and a same-slug live todo may exist by now (a slug-keyed op here would destroy that live todo's resources)
And entries removed within the window are left intact
And legacy/partial removed rows are self-healed (normalized) on the same sweep
```

```
Given a roadmap row is expired and a target/mixed snippet's delivered_by lists this slug alongside at least one other slug
When the retention maintenance sweep runs
Then workflow rewrites the snippet's frontmatter to drop just this slug from delivered_by, preserving status: target / mixed
And the snippet write completes on disk before the roadmap row hard-DELETE is issued
And after the sweep, telec sync validates the snippet cleanly with no snippet_delivered_by_unknown_slug error for this slug
```

```
Given a roadmap row is expired and a target/mixed snippet's delivered_by lists this slug as its only entry
When the retention maintenance sweep runs
Then workflow does NOT mutate the snippet's frontmatter
And workflow SKIPS the hard-DELETE for that one roadmap row on this sweep
And workflow emits a structured WARNING log naming the snippet path and the orphaning slug so the operator can resolve it
And other expired removed rows on the same sweep that are not blocked by sole-slug snippets are purged normally
```

#### UC-WFL-12: Reactivate a removed todo

```
Given a roadmap row identified by its durable row id has status=removed and has not yet been purged
And no live (active or icebox) entry exists for that row's slug
When reactivation is invoked with that roadmap row id
Then workflow clears removed_at, restores that row to its persisted prev_status (else icebox)
And replays the removed_deps snapshot back into roadmap_deps as the entry's outgoing after-edges
And the retained state, artifacts, and artifact versions are recovered intact (the entry's own footprint is indistinguishable from never-removed)
And inbound edges other todos previously held on this slug are NOT resurrected — they were scrubbed at remove time and are those other todos' state; a dependent re-declares the edge if still needed
But if a live entry already exists for that row's slug, or the id does not name a removed row, reactivation refuses and changes nothing
```

#### UC-WFL-13: Atomically rename a todo's slug

```
Given a live Todo "feature-x" with state, artifact versions, dependency
  edges in both directions, and a doc snippet whose delivered_by lists
  "feature-x"
And no non-removed entry exists for "feature-z" (only soft-removed retained
  slugs are reusable as rename targets)
And no non-terminal daemon ref is bound to "feature-x" — no operation with
  slug=="feature-x" (nor a same-cwd non-terminal operation with an
  unresolved/null slug), and no session referencing it via working_slug or
  subdir (trees/feature-x)
When `telec todo rename feature-x feature-z` is run
Then workflow re-keys the live entry's atomic unit from "feature-x" to
  "feature-z" — the denormalized todo_state.slug column and only typed
  structured slug refs (e.g. breakdown child refs; arbitrary
  prose/event-detail/free-text in the state blob is NOT rewritten, the PRD
  Won't scope), the roadmap entry, holder/child references, both
  dependency-edge directions, artifacts and full version history, snippet
  delivered_by frontmatter, and the local worktree/branch/workspace — as a
  single all-or-nothing operation
And the todos.db slug-update cascade commits in one transaction as the
  linearization point
And on commit emits workflow.todo.renamed with old_slug and new_slug
And the remote branch and daemon-DB references (operations.slug,
  sessions.working_slug, sessions.subdir) for terminal/audit and
  closed-but-revivable rows are reconciled post-commit, best-effort and
  idempotent — outside the atomic unit, never rollback-tested legs
And retained delivered/removed history rows for "feature-x" keep their
  original slug (addressed by durable row identity, not the active alias)
And if any non-removed entry already holds "feature-z", or a non-terminal
  session/operation is bound to "feature-x", the rename is refused and
  nothing changes on any surface
And if any leg fails, every completed leg is reversed (LIFO) and the system
  is left exactly as before
```

#### UC-WFL-14: Reveal removed entries through the recovery surface

```
Given one or more roadmap entries have status=removed within the retention window
And every default read path continues to hide them (the soft-delete invariant is unchanged)
When the operator requests the explicit reveal path — `telec roadmap list --include-removed` (interleaved with live entries) or `telec roadmap list --removed-only` (removed entries exclusively), or the TUI Trashed-section toggle keybinding (`x`) on the roadmap view
Then workflow returns those removed entries alongside their durable row identity and removed_at age
And the entries are visually marked as removed so the operator distinguishes them from active/icebox/delivered entries
And no other default reader (orchestration slug enumeration, integration finalize, work dispatch) sees the removed entries — the reveal is strictly opt-in to the requesting surface
And snippet validation is the named exception (per the adjacent "Soft-removed slugs remain known to the doc snippet validator" invariant): it reads the roadmap status map directly and treats removed slugs as known-but-not-delivered, never through the default-hidden filter
```

```
Given a roadmap entry has status=removed within the retention window
When the operator runs `telec todo show <slug> --include-removed` (or the equivalent opt-in flag chosen for show)
Then workflow resolves the slug against the set of removed rows for that slug
And if exactly one removed row matches, returns the full show payload (state, artifacts, version history) for that row
And if multiple removed rows share the slug, refuses with an ambiguous-slug diagnostic naming each candidate's roadmap row id and removed_at, changing nothing
And if no removed row matches the slug, refuses with a no-removed-row diagnostic
And the default `telec todo show <slug>` (without the opt-in flag) continues to refuse a slug whose only matches are removed rows
```

#### UC-WFL-15: CLI-facing reactivate addressed by slug

```
Given a roadmap entry has status=removed within the retention window
And exactly one removed row exists for the given slug
And no live (active/icebox) entry currently exists for that slug
When the operator runs `telec todo reactivate <slug>` (CLI only — the TUI restore action is UC-WFL-16, addressed by durable row id)
Then workflow resolves the slug to that unique removed row's durable row id
And dispatches the row-id-addressed reactivation primitive (UC-WFL-12)
And the entry's own footprint is restored — status flips to prev_status (legacy fallback icebox), removed_deps replays as outgoing after-edges, state/artifacts/versions become addressable through the default resolvers
And the daemon's _on_mutation('todo_updated') hook fires so cached views refresh and the entry reappears in the default reads
```

```
Given multiple removed rows share the requested slug
When the operator runs `telec todo reactivate <slug>`
Then workflow refuses with an ambiguous-slug diagnostic naming each candidate's roadmap row id and removed_at, changing nothing
And the operator may resolve the candidates through the reveal surface (UC-WFL-14) before re-attempting
```

```
Given no removed row exists for the requested slug
When the operator runs `telec todo reactivate <slug>`
Then workflow refuses with a no-removed-row diagnostic and changes nothing
```

```
Given a removed row exists for the requested slug
And a live (active/icebox) entry already exists for that slug
When the operator runs `telec todo reactivate <slug>`
Then workflow refuses with a live-twin diagnostic carrying the primitive's structured reason (live_twin_exists), changing nothing — never overwrites, merges, or silently resurrects
```

#### UC-WFL-16: TUI-facing reactivate addressed by durable row id

```
Given a roadmap entry has status=removed within the retention window
And the operator has selected that entry's trashed row in the TUI
And the rendered row carries the entry's durable roadmap.id
When the operator triggers the TUI restore keybinding on the selected row
Then workflow dispatches the row-id-addressed reactivation primitive (UC-WFL-12) directly against the selected row's roadmap.id — no slug→row-id resolution happens in the TUI, because selection already identifies the unique row
And the entry's own footprint is restored exactly as UC-WFL-12 specifies (prev_status, replayed removed_deps, retained state/artifacts/versions)
And the daemon's _on_mutation('todo_updated') hook fires so the TUI roadmap pane refreshes and the entry reappears in its restored section
And the ambiguous-slug diagnostic that UC-WFL-15 produces for the CLI cannot arise here, because the TUI never resolves a slug to a row
```

```
Given the operator triggers the TUI restore keybinding on a selected trashed row
And the dependency primitive refuses with live_twin_exists, not_removed, or invalid_removed_deps
When the dispatch returns
Then the TUI surfaces the primitive's structured reason via the existing TUI notification surface, changing nothing — no destructive side effects on refusal
```

#### UC-WFL-17: Atomically update a todo's metadata, dependencies, and content

```
Given a live todo exists for slug "<slug>"
When the operator runs `telec workflow todo update <slug> [<content>] [--artifact <name>] [--after <slugs>] [--group <label>] [--description <text>] [--kind <kind>] [--prepped]`
Then workflow applies all supplied fields in a single transaction
And dependency inputs REPLACE the entire `after` set (not patch)
And positional content writes a new artifact version (default kind `input`, or the kind named by `--artifact`)
And `--prepped` writes content as the `implementation-plan` artifact and enforces the existing prepped HITL guard
And update can NEVER move lifecycle phase (phase movement remains the prepare/work/integrate/stamp/reconcile state-machine verbs)
And on success emits workflow.todo.updated with a change_summary listing the mutated fields
And on any partial-failure rolls back so previous state is fully preserved
```

```
Given the operator runs update with mutually ambiguous content/artifact combinations
(e.g., positional content with `--prepped` AND `--artifact <other>`)
When the workflow service validates the request
Then it rejects with a typed ambiguous-update diagnostic and changes nothing
```

```
Given an artifact written by update collides with the `_artifact_name_to_state_key` retired set (test-specs, spec-review-findings)
When the workflow service validates the artifact name on the write path
Then the request is refused via the writable-allowlist gate (consistent with `telec todo artifacts write`); reads/removes of pre-cutover todos remain available
```

#### UC-WFL-18: Refinement diff for a todo (artifacts + owned snippets)

```
Given the operator wants to see refinement deltas accumulated against a slug
When they run `telec workflow todo diff <slug>`
Then workflow gathers, for that slug only:
  - each workflow.artifact's diff between its current version digest and the
    artifact's review baseline digest (notably `prd`, `architecture` index,
    `implementation-plan`)
  - each doc snippet whose frontmatter `delivered_by` list includes the slug,
    diffed against the snippet's recorded provenance SHA
And prints the unified output anchored by digest (artifacts) or git SHA (snippets)
And reports nothing for slugs that own no artifact deltas and no `delivered_by` snippet membership
```

**Baseline source — artifacts:** the per-review `approved_digest` field on
the matching `ReviewVerdictState` row (`<review>.approved_digest`) is the
contract. It is captured at verdict-approve time by
`stamp_verdict` (`teleclaude/core/next_machine/state_io.py` —
`review.approved_digest = artifact_entry.digest`) and bound to the artifact
version that earned the approve verdict. When an artifact has no
`approved_digest` (the artifact was written but never reviewed-and-approved),
the diff command emits a per-artifact diagnostic line
`baseline-absent: <artifact-kind>` and SKIPS that row; this is not an
error condition — it is the expected state for in-flight prepare phases.

**Baseline source — snippets:** the snippet's recorded provenance SHA is
captured when this delivery's slug first acquires `delivered_by` on the
snippet. The provenance is stored as a per-slug entry on the snippet's
frontmatter delivered_by metadata (provenance recording is itself part of
this delivery — see UC-WFL-18a below). When a snippet was added to
`delivered_by` BEFORE provenance recording existed (legacy snippets), the
diff command falls back to comparing against `main` HEAD and prefixes the
output with `baseline-fallback: main` so the reader knows the baseline is
approximate. When a snippet's recorded provenance SHA cannot be resolved
in the local git history, the diff command emits
`baseline-absent: <snippet-path>` and SKIPS that snippet.

#### UC-WFL-18a: Snippet-provenance SHA recording on delivered_by acquisition

```
Given an architecture (or other prepare) phase edits a doc snippet and adds a slug to its frontmatter delivered_by
When the snippet is committed (the slug first appears on the snippet's delivered_by)
Then the workflow service captures the snippet path → (slug, head_commit_sha) pair as the snippet's provenance for that slug, persisted in workflow's per-snippet provenance store
And subsequent edits to the same (snippet, slug) pair do not overwrite the provenance SHA — the baseline stays anchored to the slug's first acquisition
And UC-WFL-18 reads this provenance to compute the snippet-side diff baseline
```

Provenance recording happens at the existing snippet-commit boundary — it
is not a new dispatch. The implementation plan owns the choice of storage
(workflow_provenance table vs. a per-snippet sidecar). For snippets that
predate provenance recording, the UC-WFL-18 fallback above keeps the diff
useful even without a stored SHA.

```
Given `telec workflow artifacts diff <slug> <name> <old-digest> <new-digest>` is invoked directly
When the workflow service resolves the digests in the artifact-version history
Then it returns the digest-anchored unified diff between those two exact versions
And the todo-scoped diff (UC-WFL-18 above) is implemented in terms of this primitive — it never bypasses the digest-anchored history
```

#### UC-WFL-19: Silent creation persists state and suppresses pickup dispatch

```
Given an operator wants to enqueue substantive work without triggering autonomous pickup (e.g., bulk-queueing a backlog)
When the workflow service creates "<slug>" with substantive content and `creation_mode = silent`
Then the todo row, roadmap row, input artifact, and artifact-version row are persisted exactly as in UC-WFL-1
And workflow emits workflow.todo.created with creation_mode=silent and pickup_requested=false
And autonomous pickup consumers observe the event and explicitly do NOT dispatch
And cache, bridge-refresh, and audit consumers process the event normally
And `telec workflow todo create <slug> <content> --silent` is the CLI form that drives silent mode at the boundary
```

### v1 inventory (applies_to: v1)

The following feature spec snippets inventory the v1 workflow capabilities that this v2 target contract eventually supersedes. Each is `applies_to: v1, status: actual` and grounded in current v1 source. These feature specs are the v1 parity record; forward/target design for Category-B contract refinements lives in the domain spec, policies, and CLI-surface spec — NOT in these feature specs (per `documentation-first-development` §8a). A v1 inventory entry is corrected in place when current behavior is mis-stated; it is not made a delivery-owned target by a contract-refinement todo. They are the parity contract future v2 cutover work must satisfy or intentionally retire.

- [`todo-lifecycle-phase`](../feature/workflow/todo-lifecycle-phase.md) — Canonical `lifecycle_phase` pointer, `mark-phase` operator override, and `reconcile` evidence-driven re-derivation within a stage.
- [`state-stamping`](../feature/workflow/state-stamping.md) — `telec todo stamp` and the validated state-write boundary (`StateWriter`, `ApprovalsManager`, `ReviewManager`) that owns approvals, verdicts, skip stamps, drift acknowledgments, and finalize handoff.
- [`artifact-versioning`](../feature/workflow/artifact-versioning.md) — Multi-version workflow artifact storage with SHA256 digest, diff between digests, and cascade delete. Provenance (codebase_sha, referenced_paths) lives on the Todo state, not the artifact row.
- [`prepare-state-machine`](../feature/workflow/prepare-state-machine.md) — Phase A dispatcher: draft → PRD → architecture (optional) → plan → prepared, with PRD as the sole human approval gate and reviewer verdicts gating derived artifacts.
- [`work-state-machine`](../feature/workflow/work-state-machine.md) — Phase B dispatcher: prepared → build → review → fix → finalize → handed-off, with per-(repo, slug) single-flight lock and machine-owned `prepared → build_started` handoff.
- [`integration-state-machine`](../feature/workflow/integration-state-machine.md) — Phase C: lease-serialized 12-state machine that squash-merges from `trees/_integration/` and pushes `origin/main`; durable checkpoint enables crash recovery.
- [`worktree-prep-lifecycle`](../feature/workflow/worktree-prep-lifecycle.md) — Per-slug git worktree at `trees/<slug>/` with a digest-tracked prep marker; archives binary artifacts on delivery cleanup.
- [`dependency-graph`](../feature/workflow/dependency-graph.md) — DAG of `after` edges across roadmap entries with cycle detection at the API boundary; unmet dependencies block prepare/work dispatch.
- [`roadmap-management`](../feature/workflow/roadmap-management.md) — Per-project Roadmap CRUD via `telec roadmap {list,add,remove,move,deliver}`; explicit operator-controlled ordering; delivery transition.
- [`roadmap-icebox`](../feature/workflow/roadmap-icebox.md) — Frozen-but-recoverable state for Roadmap entries; iceboxed entries do not participate in dependency resolution. In v1, the icebox is fully DB-resident — `migrate-icebox` is a deprecated no-op.
- [`todo-creation`](../feature/workflow/todo-creation.md) — `create`, `dump`, and `design` paths to scaffold a Todo, with `--draft` and `--prepped` modes plus bug-kind helpers that route to `/next-work`.
- [`todo-split`](../feature/workflow/todo-split.md) — Split a Todo into children; in v1, the parent's `kind` is unchanged and children bootstrap with fresh `default_state` (lifecycle_phase=`draft`). The holder role is derived from `roadmap.group_slug` + `state.breakdown.todos`, not an enum value.
- [`todo-removal`](../feature/workflow/todo-removal.md) — Delete Todo state, cascade-delete artifact versions, scrub inbound dependency edges, and remove the git worktree and branches; async receipt-backed.

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
- `prepare phases`: `intake`, `prd_drafting`, `prd_human_approval`, `architecture_drafting`, `architecture_review`, `plan_drafting`, `plan_review`, `drift_analysis`, `prepared`.
- `work phases`: `pending`, `building`, `review_pending`, `review_complete`, `fixing`, `finalize_pending`, `finalize_ready`.
- `integrate phases`: per `integration-state-machine` design doc (squash, conflict-resolve, lint, test, push, deliver).
- `roadmap status` (persisted): `active`, `icebox`, `delivered`, `removed`.
- `roadmap display state` (derived for the roadmap view from persisted status + lifecycle phase): `pending`, `ready`, `in_progress`, `delivered`, `icebox`. (`removed` is persisted-only — excluded from the default view, surfaced only via the recovery UI.)
- `artifact kind`: `input`, `prd`, `architecture`, `implementation-plan`, `bug`, `quality-checklist`, `design-spec`, `deferrals`, `requirements-review-findings`, `architecture-review-findings`, `plan-review-findings`, `review-findings`. (`test-specs`, `spec-review-findings` retired; legacy read/remove only.)
- `verdict`: `approve`, `needs_work`, `needs_decision`.

## Known caveats

- Workflow is **local-first**: every operation works against the per-project Postgres schema (or SQLite in v1) without daemon dependency. The `telec` binary embeds workflow directly. The daemon is a CONSUMER of workflow events (for orchestration), not a host.
- Todo rename is target behavior delivered by `telec-todo-rename`. Its rollback-tested atomic unit excludes terminal/audit and closed-but-revivable daemon reference reconciliation for `operations.slug`, `sessions.working_slug`, and `sessions.subdir`; those rows are repaired after commit on a best-effort, idempotent basis.
- The state machine is a Rust crate (`crates/state_machine`) embedded by workflow. State machine state lives in `workflow.state_transitions`; transitions are persisted as the source of truth for phase advances.
- Per-project isolation: each project has its own `.teleclaude/todos.db` (v1 SQLite) or its own Postgres schema (v2, possibly `<project>_workflow`). No cross-project queries.
- `prepped` kind todos skip the prepare lifecycle entirely. Used when a human or agent has authored a complete implementation plan and wants to jump to build. Per the `--prepped` flag's policy: HUMAN-IN-THE-LOOP REQUIRED.
- `bug` kind todos skip the demo phase during finalize and require the orchestrator to manually mark `build complete` before advancing (per agent memory gotcha).
- The orchestrator (`teleclaude/core/next_machine/` in v1) is a CONSUMER of workflow, not part of it. The orchestrator dispatches sessions, reads workflow state, calls workflow mutations. Workflow itself has no opinion about WHO advances todos — it enforces invariants on transitions and exposes events.
- Reviewer findings artifacts are workflow artifacts (per the canonical list) even though they're produced by review sessions. The state machine treats `review-findings` artifact presence + verdict as the trigger for advance.
- **Soft-delete relies on retaining the roadmap row, not just a status flip in isolation.** In v1 SQLite, `todo_state` and `todo_artifacts` carry `ForeignKey("roadmap.id", ondelete="CASCADE")` and the active-slug uniqueness is a partial unique index over `status IN ('active','icebox')`. Soft-remove therefore keeps the roadmap row physically present (status/tombstone flip only) but, because `roadmap_deps` is slug-keyed with NO FK to `roadmap.id` and NO row identity, it MUST delete both directions of the entry's live `roadmap_deps` rows at soft-remove (outgoing edges snapshotted into the row-id-keyed `removed_deps` tombstone first; inbound discarded) — otherwise a same-slug recreate during retention would inherit or collide with them. The retention purge is then just the physical row delete: a hard `DELETE` by durable row id with the `ON DELETE CASCADE` FK (state/artifacts/versions) and **zero slug-keyed operations** — no dep scrub and no worktree/branch/workspace cleanup, since those ran at soft-remove and a same-slug live todo may exist by purge time. The full removal cascade is preserved, split by key-safety across the two phases (slug-keyed teardown at soft-remove, row-id delete at purge). The slug-keyed remove helpers are NOT reused: once reads are gated they no longer resolve `removed` rows, so purge and reactivation address the row by `roadmap.id`, not slug. `removed` falls outside the partial unique index, which is what makes slug reuse collision-free with no index change — the durable `roadmap.id` is the row identity, `slug` is only the live-entry alias, so a retained `removed` row and a fresh live row coexist exactly as a `delivered` history row already does today. The removal tombstone (`prev_status` + `removed_deps`, set only when `status=removed`) is what lets reactivation restore the entry's own footprint — status and outgoing edges — indistinguishably; inbound edges other todos held are not the entry's footprint and are not restored. The retention window is a single fixed constant shared in spirit with the closed-session sweep — not a new config surface. v1 SQLite is authoritative; the parallel v2 Rust schema mirrors this shape but is not wired into dispatch (drift deferred to `v2-workflow-cutover`).
