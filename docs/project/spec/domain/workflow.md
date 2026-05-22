---
id: project/spec/domain/workflow
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by:
- v2-workflow-cutover
- roadmap-trash-reveal-ui
- v2-workflow-cli-refinement-commands
applies_to: both
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
: Internal ordering/dependency storage for todos: rows, dependency edges, groupings, and statuses. It is surfaced to users as the ordered `telec todo list` view of "what's being worked on and what's next."

**Roadmap entry**
: One row in the roadmap, addressed by its own durable row identity (v1: `roadmap.id`). Carries: slug (the active alias), the **persisted** `status` (`active` | `icebox` | `delivered` | `removed`), `removed_at` (tombstone timestamp, set only when `status=removed`), `prev_status` and `removed_deps` (the Removal tombstone — pre-removal status and the outgoing-`after`-edge snapshot, set only when `status=removed`), `after` (live dependency slugs), optional `group` and `description`. Persisted `status` is distinct from the todo-list **display state**: the todo-list view derives `pending` / `ready` / `in_progress` from a live (`active`) entry plus its lifecycle phase, while `delivered`/`icebox` surface directly and `removed` is hidden from the default view (visible only via the recovery surface). The soft-delete invariants below operate on the persisted vocabulary.

**Holder**
: A structural roadmap row that groups child Todos. A row becomes a holder when at least one live child row sets `group_slug` to the holder slug. A holder is not an implementation Todo: it MUST NOT have a `todo_state` row, MUST NOT carry lifecycle phase, approvals, verdicts, or non-input artifacts, and MUST retain at most the original `input` artifact that seeded the split. That retained input is frozen - readable and cloneable into children, but not writable or removable through artifact mutation paths. Holder status is display-only, derived from child rows; holder dependency satisfaction is likewise computed from child delivery without mutating the holder row.

**Dependency**
: An `after` relationship between roadmap entries. Todo A is `after: [B, C]` means A cannot start until B and C are `delivered`.

**Icebox**
: Frozen-but-recoverable state for roadmap entries that aren't being actively pursued. Lives at `todos/_icebox/`. Unfreeze restores to the active todo list.

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
  - Ordering within the active todo list is derived from section membership and per-section timestamps; the system does not support manual reorder.
  - Icebox entries do NOT participate in the active dependency graph; unfreezing restores them.
  - Delivered entries remain in the todo list (visible via `--include-delivered`) for history.
  - **Removal is soft and retained.** `telec todo remove` marks the entry `status=removed`, `removed_at=now()`, and writes the removal tombstone (`prev_status` + `removed_deps`). It does NOT delete the entry's Todo state, artifacts, or artifact-version history — survival for reactivation is the point. The roadmap row itself is also retained (not physically deleted) during the retention window: the FK from `todo_state`/`todo_artifacts` to the roadmap row is `ON DELETE CASCADE`, so physically deleting the row at remove-time would destroy the very history the soft-delete exists to keep. The exception to "retain everything" is **all slug-keyed teardown**, which runs at soft-remove while the slug unambiguously names this entry: both directions of the entry's live `roadmap_deps` rows are deleted (outgoing snapshotted into `removed_deps` first; inbound discarded), and the slug's git worktree, local + remote branch, and workspace directory are cleaned up. None of this is deferred to purge: by purge time a same-slug live todo may exist, and any slug-keyed operation would destroy that live todo's edges or working resources. The durable record (row + state + artifacts + versions + tombstone) is what is retained.
  - **Removed entries are invisible to every default read path.** Every slug→row resolver, the roadmap-assembly read, cache-backed default reads, AND slug-enumeration paths (notably `list_slugs` over `todo_state` and its service/protocol wrappers) exclude `status=removed` by default — exactly as non-included delivered/icebox entries are excluded. Because soft-remove retains `todo_state` rows, any state-derived enumeration that does not gate through live roadmap status would leak removed todos; the gating contract is therefore exhaustive and includes `list_slugs`. A removed entry does not participate in the active dependency graph. **Two sanctioned reveal paths exist alongside the default-hide invariant**, both strictly opt-in: the durable row-id-addressed reactivation query (used by the recovery primitive — UC-WFL-12), and the operator-facing recovery surface (UC-WFL-14 / UC-WFL-15) — `telec todo list --include-removed` / `--removed-only`, `telec todo show <slug>` with the opt-in reveal flag, and the TUI trash-toggle. **Reveal paths split by surface — CLI reaches the workflow DB via the existing resolvers (locally for `todo list`, via the daemon REST API for `todo show`); the daemon cache contract is TUI-only:** the CLI reveal consumers each follow their existing topology. `telec todo list --include-removed` / `--removed-only` invokes `assemble_roadmap_from_db` locally with the new `include_removed` / `removed_only` keyword args. `telec todo show --include-removed` continues to call the daemon REST API (`GET /todos/{slug}/show?include_removed=true` via the existing `tool_api_request` client); the new include-removed resolver lives on the API route and assembles the row-id-backed show payload server-side. Neither CLI command consults the daemon roadmap cache snapshot. The daemon roadmap cache is scoped to the high-frequency TUI roadmap pane: it stores one snapshot per project that holds the full persisted roadmap including `removed` rows (preserving the cache-system "Single Snapshot Per Scope" invariant); every default cache accessor applies a filter at read time that excludes `removed`, so the TUI's default sections continue to see exactly what the default resolvers expose; the TUI Trashed section reads the SAME cache snapshot with the filter relaxed via a per-call opt-in flag. The filter — never the snapshot — is what changes between default and reveal paths on the TUI side, and the cache shape itself never widens to a second-snapshot variant. Orchestration slug enumeration, integration finalize, and work dispatch always use the default-filtered path.
  - **Removed entries do not collide with slug reuse.** The active-slug uniqueness constraint covers only `status IN ('active','icebox')`; `removed` sits outside that predicate, so a freshly created entry may reuse a slug while a removed-and-retained twin still exists. No uniqueness-index change is required. Crucially, a removed entry holds NO live slug-keyed `roadmap_deps` rows (they were scrubbed at soft-remove, outgoing parked in the row-id-keyed `removed_deps` tombstone), so a same-slug recreate starts with a clean dependency set and cannot inherit the removed entry's edges. Reactivation (which restores `removed_deps`) is itself fail-closed against a live same-slug twin, so the two can never both hold live edges for the slug.
  - **Retention finalization is automatic and row-id-only.** Routine maintenance hard-purges entries with `removed_at` older than the fixed retention window (the same window applied to closed sessions) by hard-`DELETE`ing the retained roadmap row **by durable row id**; the `ON DELETE CASCADE` FK removes state/artifacts/versions. The purge performs **zero slug-keyed operations** — no `roadmap_deps` scrub (not even defensively) and no worktree/branch/workspace cleanup — because all slug-keyed teardown ran at soft-remove and a same-slug live todo may exist by purge time; a slug-keyed op here would destroy that live todo's edges or resources. The full removal cascade is preserved, split across the two phases: all slug-keyed teardown at soft-remove, physical row + FK cascade at purge. It does not call the slug-keyed remove helpers. Each sweep self-heals legacy/partial rows. This finalizes an already-explicit operator removal after a recovery grace period; it is not blind pruning of live durable data.
  - **Decision-time orphan refusal at soft-remove — one guarded primitive, one serialized critical section.** Every soft-remove caller — `telec todo remove` (CLI → `/todos/remove` → operations service → `execute_todo_remove`) and any programmatic caller (e.g. `WorkRoadmapService.remove`) — routes through the single DB primitive `TodosDb.soft_remove_from_roadmap`. The primitive is the guarded boundary; no caller bypasses the refusal. Inside the primitive, the orphan scan and the status transition are one serialized critical section: a project-scoped `asyncio.Lock` owned by the per-project `TodosDb` instance is acquired before the DB session is opened, and the session begins with `BEGIN IMMEDIATE` so the SQLite write lock is held from the first read. Inside this critical section the primitive (1) reads the live `roadmap_status` map, (2) scans on-disk snippet frontmatter via the canonical `_iter_snippet_files` primitive in `docs_reconcile` — no parallel scanner — classifying each `delivered_by` reference against the live map, (3) if any `target` / `mixed` snippet's `delivered_by` would be left with no live deliverer (a "live deliverer" being any slug whose roadmap status is anything other than `removed` — active, icebox, delivered all count as live), raises `RemoveRefused` and rolls back; the row's status is unchanged, no tombstone is written, no `removed_deps` snapshot is taken, no snippet files are touched, and no slug-keyed teardown runs, (4) otherwise flips status to `removed`, writes the tombstone, scrubs both directions of `roadmap_deps`, and commits. The lock + `BEGIN IMMEDIATE` together guarantee that two concurrent removes of slugs sharing a snippet cannot both observe each other as live: the second remove blocks on the lock, and when it acquires the lock the first remove has already committed its status flip, so the second scan correctly sees the first as `removed` and refuses. The structured `RemoveRefused` payload names every blocking snippet, the slug's role in each (sole entry vs. last-live-among-removed), the live-deliverer count, and the other removed deliverers, and is propagated through the operation runner's structured-error pipeline (durable `Operation.error_payload` JSON column, `OperationStatusDTO.error_payload` field, CLI structured rendering). The invoking agent reads the structured error and decides the next action in its own flow (dispatch a doc-update lifecycle op to drop the orphaning reference, then retry; or abandon the remove). This in-flow refusal is what makes the sole-slug-orphan case at purge time unreachable by construction; no `blocked` field, no queued drift task, no auto-flip on someone else's behalf.
  - **Retention purge is atomic with documentation reconciliation AND a pathspec-scoped git commit, with durable per-row retry state.** A retained roadmap row may still be named alongside other live deliverers on `target` / `mixed` doc snippets at purge time (the decision-time refusal guarantees at least one other live deliverer exists for every snippet that referenced the slug). The retention sweep couples the per-row hard-`DELETE` with snippet frontmatter reconciliation AND a pathspec-scoped local `git commit` on the project root so that (a) no snippet ever points at a slug whose roadmap row no longer exists, and (b) no snippet write is left uncommitted in the daemon's working tree after a sweep returns. Reconciliation reuses the canonical frontmatter primitives in `docs_reconcile` (the same parse/render engine the post-delivery flip uses); no duplicate parse/render is introduced. The purge handles only the **multi-slug** case — drop the purged slug from `delivered_by`; the snippet keeps its `status: target` / `mixed`; no other frontmatter changes. If the sweep ever observes a snippet whose `delivered_by` would be left with zero live deliverers after this row's purge — i.e. the unreachable sole-slug-orphan case — that is a contract violation in the soft-delete refusal logic upstream and the sweep raises a defensive `RuntimeError` naming the snippet and the roadmap row. It never silently skips, never sets `blocked`, never auto-flips, never queues work. **Durable per-row retry record:** the `roadmap` table carries a `pending_purge_paths: TEXT NULLABLE` column (JSON-encoded list of snippet paths relative to project root) used solely by the sweep. On a fresh pass (no prior `pending_purge_paths` on the row) the sweep first computes the mutation list, then applies the foreign-edit dirty-path precondition against the candidate paths, and only if every candidate path is clean does it persist `pending_purge_paths` and write files — the durable record exists before any file write but after the dirty-path gate; a dirty candidate path on a fresh pass aborts the row with no persist, no write, no commit. On success this column is cleared; on commit failure it stays populated so the next sweep can resume the row deterministically. **Per-row ordering is fixed:** (1) read the row, including `pending_purge_paths`; (2) if `pending_purge_paths` is NULL (fresh pass), compute the snippet mutation list via the shared reconcile engine (multi-slug-only), then apply the working-tree-dirty precondition to those candidate paths — because nothing is sweep-owned yet, ANY candidate path showing dirty in `git status --porcelain` is by definition a foreign edit and aborts this row's iteration with a structured INFO log (no persist, no write, no stage, no commit); only if every candidate path is clean does the sweep persist the computed path list via `set_pending_purge_paths` and commit (durable record before any file write); if `pending_purge_paths` was already non-NULL (retry pass), reuse the persisted list, skip the reconcile compute, and treat those paths as sweep-owned residue from a prior failed pass (NOT foreign — explicitly permitted to be dirty/staged); foreign edits to paths outside `pending_purge_paths` cannot block this row's commit because the commit pathspec is exactly `pending_purge_paths`; (3) for each path in `pending_purge_paths`, write the file (or verify it already matches target state when re-entering after a prior failed commit); (4) snapshot `PRE_STAGED = git diff --cached --name-only` BEFORE staging — the set of files already staged outside this sweep, which TeleClaude's dirty-main contract explicitly permits and which forms the baseline for the verification deltas; (5) `git add -- <path1> <path2> ...` restricted to the exact `pending_purge_paths`, never `git add -A` / `git add .`; (6) **pre-commit staged-set verification (Layer 2):** `git diff --cached --name-only` must equal `PRE_STAGED ∪ pending_purge_paths` (set equality after normalisation) — anything else means a pathspec quoting bug, a pre-commit hook fired before `git commit` and staged extras outside the union, or a foreign stage that arrived during the commit window; if unequal, emit a structured INFO log naming the staged-set diff and abort this row's iteration; (7) `git commit -m <stable-structured-message> -- <path1> <path2> ...` (pathspec form, no `--no-verify` — the project's pre-commit hooks run exactly as they would for any human commit; the pathspec form restricts the commit to exactly the named paths regardless of what else is staged, defence-in-depth alongside the staged-set verification); (8) **post-commit index/worktree verification (Layer 3):** the Layer 2 check observes the index BEFORE `git commit` runs and therefore CANNOT catch files staged or modified by pre-commit hooks DURING the commit; after `git commit` returns zero the sweep runs (a) `git diff --cached --name-only` — the result MUST contain only entries from `PRE_STAGED` (any NEW entry not in `PRE_STAGED` means a hook staged something during the commit; any path from `pending_purge_paths` still present means the pathspec-restricted commit did not include it) AND (b) `git status --porcelain` parsed and filtered to entries whose paths are NOT in `PRE_STAGED` AND NOT in `pending_purge_paths` (must be empty — any such NEW entry means a hook modified a file outside the pathspec, or a foreign edit landed during the commit window); if either check fails, the sweep treats this row's iteration as a failure (emit a structured INFO log naming `path`, `slug`, `roadmap_id`, the `verification_failure_reason`, and the offending staged-set or porcelain entries; do NOT clear `pending_purge_paths`; do NOT call `purge_one_removed`); the committed snippet edits are NOT rolled back because they are already correct in HEAD; persistent post-commit verification failure across sweeps means the hook configuration is rejecting the sweep's pathspec contract and is a real bug to investigate as code, never queued as drift; (9) on commit success AND post-commit verification clean, call `clear_pending_purge_paths(row_id)` then `purge_one_removed(row_id)` (the hard-`DELETE`). Each step is gated on the previous; the inverse ordering is forbidden because it leaves the docs layer in a state `telec sync` would reject or the working tree dirty. The commit invocation reuses the existing `_run_git_cmd` helper in `teleclaude/core/next_machine/delivery.py` — no parallel git wrapper, no raw `subprocess.run(["git", ...])`. The commit message is stable and structured (e.g. `chore(roadmap): purge <slug>; reconcile delivered_by in <N> snippets`) so the resulting git history is self-explanatory. **Working-tree precondition (foreign-edit attribution):** a path that appears in any expired row's `pending_purge_paths` and is dirty is by definition this sweep's residue from a prior failed pass and proceeds to retry. A path that is dirty and is NOT in any `pending_purge_paths` is by definition a foreign edit. The two are distinguished by durable state, not by heuristic. If foreign edits overlap a candidate row's pathspec, the sweep skips that row for this hour, emits a structured INFO log with `path`, `slug`, `roadmap_id`, and the dirty-precondition reason, and continues with the remaining expired rows; the in-progress edit is never overwritten, staged, or committed. The next sweep retries; the situation clears autonomously when the editor finishes. **Commit-failure handling (durable retry, two sub-cases):** if `git commit` returns non-zero, or returns zero but post-commit verification fails, the sweep emits a structured INFO log with `path`, `slug`, `roadmap_id`, and the `commit_failure_reason` (or `verification_failure_reason`), does NOT clear `pending_purge_paths`, and does NOT call `purge_one_removed`. The snippet file is left in its target state on disk; the committed snippet edits, if any, remain in HEAD. The next sweep reads the same row, observes the populated `pending_purge_paths`, skips the reconcile-compute step (paths are known), and discriminates two sub-cases by comparing each path's on-disk content to `git show HEAD:<path>`: (a) **files-match-HEAD sub-case** (the prior `git commit` succeeded and only the post-commit verification tripped on hook residue): the sweep SKIPS re-staging and re-committing — re-staging files that match HEAD stages nothing, and the Layer 2 staged-set equality check would then see only the unrelated foreign/hook residue and trip again. Instead the sweep snapshots `PRE_STAGED` fresh and re-runs only the Layer 3 post-commit verification checks (the `git diff --cached --name-only` ⊆ `PRE_STAGED` check and the `git status --porcelain` filtered-NEW check) against the current working tree; on pass, the sweep clears `pending_purge_paths` and calls `purge_one_removed`; on persistent fail (the hook residue is still there), emit structured INFO and continue — the row is re-encountered next sweep. (b) **Files-do-not-match-HEAD sub-case** (the prior `git commit` returned non-zero before HEAD updated, or a file has since diverged): the sweep proceeds with the full retry — re-apply the mutation if the file diverged (no-op write if already in target), snapshot `PRE_STAGED`, re-stage exactly `pending_purge_paths` via `git add -- <pending_purge_paths>`, re-run the Layer 2 staged-set equality check (`PRE_STAGED ∪ pending_purge_paths`), re-issue `git commit -- <pending_purge_paths>`, and re-run Layer 3 post-commit verification. The discriminator is content equality with HEAD, not heuristic. The dirty-path precondition does NOT trip on the sweep's own residue because the residue paths are in `pending_purge_paths`. Persistent commit failure is a real bug (the hook is rejecting something it shouldn't) that surfaces as code investigation, never as drift queued on anyone. The commit is local — pushing to remote is owned by the integration flow, never by the sweep. Concurrent `telec sync` therefore never observes a snippet whose `delivered_by` names a vanished roadmap row, and the daemon's working tree is never left dirty after a sweep returns.
  - **Reactivation is fail-closed.** The primitive takes a **durable roadmap row id** (not a slug — repeated remove/recreate can leave multiple `removed` rows per slug). It fully recovers that row's own footprint (roadmap row + state + artifacts + versions) to the persisted `prev_status` (legacy-row fallback `icebox`) and replays `removed_deps` as the entry's outgoing `after` edges — making the entry indistinguishable from never-removed at its own aggregate level. Inbound edges other todos held on the slug are NOT resurrected: they were scrubbed at remove time and are those other todos' state (a dependent re-declares if still needed). It refuses and mutates nothing if a live (`active`/`icebox`) entry exists for that row's slug, or if the id does not name a `removed` row — it never overwrites, merges, or silently resurrects. Targeted/rename restore is out of scope for this context (it belongs to the recovery UI, which supplies the row id).
- **Identifier:** the per-project roadmap is unique per project; no separate identifier.
- **Lifecycle:** Created when the project is initialized. Viewed through `telec todo list`; mutated by `telec todo create/remove/freeze/unfreeze/deliver`, dependency-setting primitives, lifecycle state machines, and recovery primitives. `remove` is soft + retained (above), finalized by the maintenance retention purge or reversed by reactivation. Persists for the project's lifetime.

### Banded ordering

The default roadmap order is derived, not manually positioned. Active rows are split into a **Ready** band followed by an **In prep** band. A row enters Ready only when all `after` dependencies are delivered and either its kind is `bug` / `prepped` or its lifecycle phase is one of `prepared`, `build_started`, `build_complete`, `review_changes_requested`, or `review_approved`; Ready rows sort by `ready_since` (falling back to `updated_at`) and then slug. In-prep rows sort by `updated_at` and then slug. Delivered and icebox rows are optional sections outside the active bands; delivered sorts newest-first by `delivered_at`, icebox newest-first by `updated_at`. Removed rows are persisted for recovery but absent from the default order.

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
- **Emitted when:** a new todo is added to the todo list (via `create`, the
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

##### v1 partial-shape (transitional)

The v1 `/todos/dump` route (`teleclaude/api/todo_routes.py`) emits seven
fields: `slug`, `kind` (canonical-mapped via `map_v1_kind_to_canonical`),
`creation_mode`, `pickup_requested`, `lifecycle_phase`, `created_at`, and
`project_path`.

Six of those seven are canonical fields. `project_path` is not part of the
canonical nine-field contract above — v1 carries it as a bridge-forward
extra because the v1 runtime has no `project_id`; the canonical producer
schema uses `project_id` from which bridge consumers derive `project_path`
via the existing `project_id → project_path` map.

The three canonical fields absent on v1-emitted events are `todo_id`,
`project_id`, and `created_by_principal`.

Consumers MUST treat those three fields as optional and apply safe defaults
when ingesting events that may originate from a v1 emitter. The Rust v2
`WorkflowService` handles this via serde defaults on the `TodoCreated` struct
so v2 code can consume v1 events without panicking on missing fields.

This partial shape is a transitional constraint, not the target contract. The
`v2-workflow-cutover` delivery retires it: the v2 route emits the full
canonical payload above, and v1-compatibility handling (serde defaults on
optional fields, downstream `.unwrap_or_default()` reads) is removed at
cutover.

#### `workflow.todo.updated`

- **Producer:** `workflow`
- **Emitted when:** any mutation to a todo's metadata or artifacts that does NOT change its phase (artifact write, description change, dependency edit).
- **Payload:** `slug`, `updated_at`, `change_summary` (string), `updated_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (live todo-list view refresh), `telec-tui` (cache invalidation).
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
- **Emitted when:** an operator changes a dependency edge, freezes/unfreezes an entry, or the delivery path stamps the entry delivered.
- **Payload:** `slug`, `change_type` (`dependency_changed` | `frozen` | `unfrozen` | `delivered`), `details`, `moved_at`, `moved_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (todo-list view refresh), `telec-tui` (cache invalidation).
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
And validates `upstream-slug` exists in the todo list
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

#### UC-WFL-6: Todo entry moves to icebox

```
Given an operator decides a todo entry is not currently being pursued
When they run `telec todo freeze <slug>`
Then workflow moves the entry's filesystem to todos/_icebox/<slug>/
And marks the todo entry status=icebox
And the entry no longer participates in dependency resolution for active entries
And emits workflow.roadmap.entry_moved with change_type=frozen
And `telec todo list` no longer shows it by default
```

#### UC-WFL-7: Delivery stamps the integration outcome

```
Given a todo has completed the integrate state machine successfully
And integration has reconciled and staged any doc snippets whose delivered_by includes this slug in the delivery worktree before creating the delivery commit
When the integrator stamps the delivery commit (workflow.deliver(slug, commit_sha))
Then workflow sets the todo's stage=delivered, delivery_commit=<sha>
And emits workflow.todo.delivered
And the todo entry status becomes delivered
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
Given an operator or agent runs `telec todo remove <slug>`
And no target/mixed snippet's delivered_by would be left with zero live deliverers if this slug were soft-removed (a live deliverer is any slug whose roadmap status is active, icebox, or delivered — soft-removed slugs do not count)
Then workflow marks the todo entry status=removed and removed_at=now()
And captures prev_status and snapshots the entry's outgoing after-edges into the removal tombstone (removed_deps)
And retains the Todo state, all artifacts, and all artifact versions (no cascade delete)
And performs ALL slug-keyed teardown now, while the slug unambiguously names this entry: deletes from the live roadmap_deps table BOTH the entry's outgoing edges (slug == removed_slug) and inbound edges (depends_on == removed_slug); and removes the slug's git worktree, local + remote branch, and workspace directory
And the entry disappears from every default CLI/TUI/cache read
And a new todo may immediately be created reusing the same slug with no inherited dependencies, no worktree/branch clash, and no collision
```

```
Given an operator or agent runs `telec todo remove <slug>`
And at least one target/mixed snippet's delivered_by lists this slug AND every other slug in that snippet's delivered_by is itself in status=removed (or this slug is the sole entry)
When workflow synchronously scans on-disk snippet frontmatter via the canonical _iter_snippet_files primitive before any DB state transition
Then workflow refuses the remove with a structured error naming every blocking snippet path, the slug's role in each (sole entry vs. last-live-among-removed), and the live-deliverer count
And no DB state changes — the roadmap row's status is unchanged, no tombstone is written, no removed_deps snapshot is taken
And no snippet files are mutated
And no slug-keyed teardown runs — the worktree, branches, and workspace remain intact
And the invoking agent reads the structured error and resolves the orphan (drops the delivered_by reference via a doc-update lifecycle op, or abandons the remove) before retrying
```

#### UC-WFL-11: Retention purge finalizes an expired removal

```
Given a todo entry has status=removed with removed_at older than the retention window
When the routine maintenance sweep runs
Then workflow hard-DELETEs the retained roadmap row by its durable row id
And the ON DELETE CASCADE FK removes state, artifacts, and artifact versions
And the purge performs ZERO slug-keyed operations — no worktree/branch/workspace cleanup and no roadmap_deps scrub — because all slug-keyed teardown already ran at soft-remove and a same-slug live todo may exist by now (a slug-keyed op here would destroy that live todo's resources)
And entries removed within the window are left intact
And legacy/partial removed rows are self-healed (normalized) on the same sweep
```

```
Given a roadmap row is expired and one or more target/mixed snippets' delivered_by lists this slug alongside at least one other live deliverer (the decision-time orphan refusal at soft-remove guarantees no snippet can be sole-slug-dependent on a removed slug)
And the row has no prior `pending_purge_paths` recorded (fresh pass)
When the retention maintenance sweep runs against the project's working tree
Then workflow computes the snippet mutation list, applies the dirty-path precondition to those candidate paths (because nothing is sweep-owned yet, any dirty candidate path is a foreign edit and aborts this row's iteration with no persist/write/stage/commit), and only when every candidate is clean does workflow persist `pending_purge_paths` and proceed
And workflow writes each affected snippet's frontmatter to drop just this slug from delivered_by, preserving status: target / mixed; reconciliation reuses the canonical docs_reconcile primitives (no duplicate parse/render)
And workflow snapshots `PRE_STAGED = git diff --cached --name-only` BEFORE staging — the set of files already staged outside this sweep, which TeleClaude's dirty-main contract explicitly permits and which forms the baseline for the Layer 2/3 verification deltas
And workflow stages the mutated snippet paths via `git add -- <path>` against the project root, restricted to exactly the paths the sweep is mutating in this iteration (never `git add -A` / `git add .`); the existing _run_git_cmd helper in teleclaude/core/next_machine/delivery.py is reused (no parallel git wrapper)
And workflow runs a Layer 2 pre-commit staged-set verification: `git diff --cached --name-only` MUST equal `PRE_STAGED ∪ pending_purge_paths` (set equality after normalisation); any other result aborts this row's iteration with structured INFO before the commit issues
And workflow runs a non-interactive `git commit -- <pending_purge_paths>` against the project root (pathspec form, no --no-verify; the project's pre-commit hooks run exactly as they would for any human commit) with a stable structured message naming the purged slug and the snippet count
And workflow runs the Layer 3 post-commit index/worktree verification: (a) `git diff --cached --name-only` MUST contain only entries from `PRE_STAGED` (no new staged entries from hook activity; no leftover `pending_purge_paths` entries from a missed commit), AND (b) `git status --porcelain` filtered to entries NOT in `PRE_STAGED` AND NOT in `pending_purge_paths` MUST be empty (no hook-modified file outside the pathspec, no foreign edit landed during the commit window)
And only after Layer 3 verification passes does workflow clear `pending_purge_paths` and hard-DELETE the roadmap row by durable row id
And after the sweep returns, `git status` on the project root shows no NEW modified snippet files from this sweep beyond what was already dirty before the sweep ran, and `telec sync` validates cleanly
```

```
Given a roadmap row is expired and the durable `pending_purge_paths` column on that row is empty (no prior sweep has claimed snippet paths for this row)
And a target/mixed snippet the sweep would mutate is already modified in the working tree from a non-sweep source (someone is mid-edit, or another tool has touched the file)
When the retention maintenance sweep encounters that row
Then workflow uses `pending_purge_paths` as the sweep's ownership signal — only paths recorded in `pending_purge_paths` are sweep-owned; every other dirty path is a foreign edit
And because no path is yet sweep-owned for this row, the foreign edit blocks this row's iteration: workflow does NOT mutate the snippet file, does NOT persist `pending_purge_paths`, does NOT call `git add`, does NOT call `git commit`, and does NOT hard-DELETE the roadmap row
And workflow emits a structured INFO log naming `path`, `slug`, `roadmap_id`, and the dirty-precondition reason
And workflow continues with the remaining expired rows on this sweep that are not blocked by working-tree preconditions of their own
And the next maintenance sweep retries this row; the situation resolves itself when the editor finishes their work or backs out their changes — no drift task is queued on anyone
```

```
Given a roadmap row is expired and the snippet frontmatter mutation completes on disk against the paths recorded in `pending_purge_paths`, but the subsequent pathspec-restricted `git commit -- <pending_purge_paths>` either returns non-zero (pre-commit hook rejection, staged-set mismatch, write race) OR returns zero but the post-commit Layer 3 verification trips (hook auto-staged an unrelated file, hook modified a file outside the pathspec)
When the retention maintenance sweep observes the failure
Then workflow does NOT clear `pending_purge_paths`, does NOT hard-DELETE the roadmap row, and does NOT rollback the file writes or HEAD
And workflow leaves the snippet files in their mutated (target-state) form on disk; the durable `pending_purge_paths` record is the receipt that this residue is sweep-owned, not a foreign edit
And workflow emits a structured INFO log naming `path`, `slug`, `roadmap_id`, and the `commit_failure_reason` or `verification_failure_reason`
And on the next maintenance sweep this row is re-encountered with `pending_purge_paths` already populated, so workflow recognises the residue as sweep-owned (NOT foreign) and does NOT skip the row on the dirty-precondition
And workflow discriminates two sub-cases by comparing each path's on-disk content to `git show HEAD:<path>`:
And in the **files-match-HEAD sub-case** (every path matches HEAD — the prior `git commit` succeeded, only the post-commit verification tripped on hook residue) workflow SKIPS re-stage and re-commit (re-staging clean files would stage nothing and Layer 2 staged-set equality (`PRE_STAGED ∪ pending_purge_paths`) would trip on the residual foreign/hook entries); workflow snapshots `PRE_STAGED` fresh and re-runs ONLY the Layer 3 post-commit verification checks (`git diff --cached --name-only` ⊆ `PRE_STAGED`, and `git status --porcelain` filtered to NEW entries not in `PRE_STAGED` and not in `pending_purge_paths` empty); on Layer 3 pass, workflow clears `pending_purge_paths` and calls `purge_one_removed`; on persistent Layer 3 fail (hook residue still there), workflow emits structured INFO and continues — row re-encountered next sweep
And in the **files-do-not-match-HEAD sub-case** (the prior `git commit` returned non-zero before HEAD updated, or a file has since diverged) workflow proceeds with the full retry — re-apply the mutation for any path whose on-disk content diverged from target (no-op write if already in target), snapshot `PRE_STAGED`, re-stage exactly `pending_purge_paths` via `git add -- <pending_purge_paths>`, re-run the Layer 2 staged-set equality check, re-issue `git commit -- <pending_purge_paths>`, re-run Layer 3 post-commit verification
And on full-retry success workflow clears `pending_purge_paths` to NULL and hard-DELETEs the roadmap row
And persistent failure across sweeps surfaces as a real bug (the hook configuration is rejecting the sweep's pathspec contract) for a worker to investigate as code; no drift task is queued
```

```
Given a roadmap row is expired and a target/mixed snippet's delivered_by would be left with zero live deliverers after this row's purge (an unreachable state under the decision-time orphan refusal at soft-remove)
When the retention maintenance sweep encounters that snippet during reconciliation
Then workflow raises a defensive RuntimeError naming the snippet path and the roadmap row id, and does NOT mutate the file, does NOT call `git add` / `git commit`, and does NOT hard-DELETE the row
And the RuntimeError indicates a contract violation upstream in the soft-delete refusal logic — a code bug, not a runtime data condition; investigation kicks off as a code task, not as drift bookkeeping
And the sweep does not silently skip, does not set `blocked`, and does not auto-flip the snippet
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
Given one or more todo entries have status=removed within the retention window
And every default read path continues to hide them (the soft-delete invariant is unchanged)
When the operator requests the explicit reveal path — `telec todo list --include-removed` (interleaved with live entries) or `telec todo list --removed-only` (removed entries exclusively), or the TUI Trashed-section toggle keybinding (`x`) on the todo-list view
Then workflow returns those removed entries alongside their durable row identity and removed_at age
And the entries are visually marked as removed so the operator distinguishes them from active/icebox/delivered entries
And no other default reader (orchestration slug enumeration, integration finalize, work dispatch) sees the removed entries — the reveal is strictly opt-in to the requesting surface
And snippet validation is the named exception (per the adjacent "Soft-removed slugs remain known to the doc snippet validator" invariant): it reads the roadmap status map directly and treats removed slugs as known-but-not-delivered, never through the default-hidden filter
```

```
Given a todo entry has status=removed within the retention window
When the operator runs `telec todo show <slug> --include-removed` (or the equivalent opt-in flag chosen for show)
Then workflow resolves the slug against the set of removed rows for that slug
And if exactly one removed row matches, returns the full show payload (state, artifacts, version history) for that row
And if multiple removed rows share the slug, refuses with an ambiguous-slug diagnostic naming each candidate's roadmap row id and removed_at, changing nothing
And if no removed row matches the slug, refuses with a no-removed-row diagnostic
And the default `telec todo show <slug>` (without the opt-in flag) continues to refuse a slug whose only matches are removed rows
```

#### UC-WFL-15: CLI-facing reactivate addressed by slug

```
Given a todo entry has status=removed within the retention window
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
Given a todo entry has status=removed within the retention window
And the operator has selected that entry's trashed row in the TUI
And the rendered row carries the entry's durable roadmap.id
When the operator triggers the TUI restore keybinding on the selected row
Then workflow dispatches the row-id-addressed reactivation primitive (UC-WFL-12) directly against the selected row's roadmap.id — no slug→row-id resolution happens in the TUI, because selection already identifies the unique row
And the entry's own footprint is restored exactly as UC-WFL-12 specifies (prev_status, replayed removed_deps, retained state/artifacts/versions)
And the daemon's _on_mutation('todo_updated') hook fires so the TUI todo-list pane refreshes and the entry reappears in its restored section
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
- [`work-state-machine`](../feature/workflow/work-state-machine.md) — Phase B dispatcher: prepared → build → review → fix → finalize_ready (terminal), with per-(repo, slug) single-flight lock and machine-owned `prepared → build_started` handoff. The `todo_finalize_ready` integration event is emitted by the TodosDb write-state chokepoint hook, not from within the work-step, so any writer that lands the terminal phase (work-machine claim, reconcile, direct `mark-phase`) produces the event. v1 TodosDb does not serialize writers per project, so the chokepoint provides at-least-once emission per actual `* → finalize_ready` transition; the `IntegrationTriggerCartridge`'s `_spawned_event_keys` dedup on `(slug, sha, worker_session_id)` collapses duplicates to exactly-one integrator spawn, and the integrator's `integration/main` singleton lease serializes spawns into a single integration run per slug.
- [`integration-state-machine`](../feature/workflow/integration-state-machine.md) — Phase C: lease-serialized 12-state machine that squash-merges from `trees/_integration/` and pushes `origin/main`; durable checkpoint enables crash recovery.
- [`worktree-prep-lifecycle`](../feature/workflow/worktree-prep-lifecycle.md) — Per-slug git worktree at `trees/<slug>/` with a digest-tracked prep marker; archives binary artifacts on delivery cleanup.
- [`dependency-graph`](../feature/workflow/dependency-graph.md) — DAG of `after` edges across roadmap entries with cycle detection at the API boundary; unmet dependencies block prepare/work dispatch.
- [`todo-management`](../feature/workflow/todo-management.md) — Per-project ordered todo-list access through todo-scoped commands; derived section ordering; delivery transition.
- [`todo-icebox`](../feature/workflow/todo-icebox.md) — Frozen-but-recoverable state for Todo entries; iceboxed entries do not participate in dependency resolution.
- [`todo-creation`](../feature/workflow/todo-creation.md) — `create`, `dump`, and `design` paths to scaffold a Todo, with `--draft` and `--prepped` modes plus bug-kind helpers that route to `/next-work`.
- [`todo-split`](../feature/workflow/todo-split.md) — Split a Todo into children; in v1, children bootstrap with fresh `default_state` (lifecycle_phase=`draft`). The parent becomes a stateless holder derived from live child `roadmap.group_slug` rows; its retained input artifact is frozen and no `todo_state` row may exist for it.
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
- `todo-list display state` (derived for the todo-list view from persisted roadmap status + lifecycle phase): `pending`, `ready`, `in_progress`, `delivered`, `icebox`. (`removed` is persisted-only — excluded from the default view, surfaced only via the recovery UI.)
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
