# Implementation Plan: mirror-runtime-isolation

## Overview

Two sequential lanes. Lane A protects API responsiveness (containment). Lane B
stabilizes mirror identity and convergence (correctness). Each lane is
incrementally mergeable with rollback boundaries.

Review findings addressed:
- Finding 1 (unmarked inferences): acknowledged — implementation honors the
  requirements as written; inferred items are treated as grounded codebase facts.
- Finding 2 (config surface): Task A6 specifies the config key and wizard path.
- Finding 3 (measurement thresholds): Task A5 defines concrete gate criteria.

---

## Lane A: Containment

### Task A1: Canonical transcript allowlist contract

**What**

Rewrite `teleclaude/utils/transcript_discovery.py` to use a positive allowlist
instead of open-ended globbing.

Current problems:
- Claude: no exclusion for `/subagents/` subdirectories under projects.
- Codex: line 33 explicitly appends `~/.codex/.history/sessions` as a second
  search root — this is non-canonical.

Changes:
1. Add `is_canonical(path: Path, agent: AgentName) -> bool` that encodes:
   - Claude: reject any path containing `/subagents/` in its components.
   - Codex: reject any path under `~/.codex/.history/`.
   - Gemini: all matches canonical (no exclusions defined).
2. Remove the `.history/sessions` append at line 33.
3. Apply `is_canonical` filter in the candidate loop before appending.
4. Export `is_canonical` from the module for use by worker/search.

The Claude `projects/` root override (lines 28–31) is preserved — it correctly
narrows Claude discovery to project-scoped transcripts.

**Why**

The requirements mandate a positive allowlist. Blacklist-style exclusions drift.
Without this, reconciliation processes non-canonical transcripts that inflate the
hot corpus and cause write pressure. Every downstream task depends on this
contract.

**Verification**

- Test: `discover_transcripts()` returns only allowlisted canonical paths.
- Test: Claude subagent paths excluded (fixture with `subagents/` directory).
- Test: Codex `.history` paths excluded (fixture with `.history/` directory).
- Test: Gemini canonical paths included unchanged.
- Test: `is_canonical()` returns expected results for each agent.
- Existing discovery ordering test still passes.

**Referenced files**

- `teleclaude/utils/transcript_discovery.py` (modify)
- `tests/unit/test_transcript_discovery.py` (extend)

---

### Task A2: Prune non-canonical mirrors from existing DB

**What**

Add migration `teleclaude/core/migrations/0XX_prune_non_canonical_mirrors.py`
that removes mirror rows whose `metadata.transcript_path` matches non-canonical
patterns.

The migration:
1. Reads all mirror rows.
2. Parses `metadata` JSON for `transcript_path`.
3. Applies `is_canonical` from A1.
4. Deletes non-canonical rows (and their FTS entries via existing triggers).
5. Logs the count of pruned rows.

**Why**

Existing mirror data includes non-canonical entries from before the allowlist.
Without pruning, reconciliation convergence metrics are polluted and the
measurement gate (A5) would measure stale data. Pruning also reduces DB/FTS
size, directly lowering write pressure.

**Verification**

- Test: migration deletes non-canonical rows and preserves canonical rows.
- Test: FTS entries for deleted rows are cleaned up.

**Referenced files**

- `teleclaude/core/migrations/0XX_prune_non_canonical_mirrors.py` (create)
- `tests/unit/test_mirror_prune_migration.py` (create)

---

### Task A3: Thread-isolated reconciliation worker

**What**

Move `MirrorWorker.run_once()` execution from the daemon's asyncio event loop
into a separate OS thread via `asyncio.to_thread()`.

The current worker is disabled (lines 2254–2257 in `daemon.py` are commented
out, `worker.py:run()` has an early return). The worker's I/O is already all
synchronous (filesystem stat/read + sqlite3 via the sync `store.py` functions),
but it's declared `async def`. Running thousands of these per cycle blocks the
event loop.

Changes to `teleclaude/mirrors/worker.py`:
1. Extract synchronous reconciliation body into `_reconcile_sync() -> ReconcileResult`
   where `ReconcileResult` is a dataclass with `discovered`, `processed`,
   `skipped_unchanged`, `skipped_no_context`, `duration_s` fields.
2. `run_once()` becomes: `return await asyncio.to_thread(self._reconcile_sync)`.
3. Remove the early return in `run()`.

Changes to `teleclaude/mirrors/generator.py`:
- Add `generate_mirror_sync()` — the function body is already synchronous.
  `generate_mirror` (async) delegates to it for backward compat with event handlers.

Changes to `teleclaude/daemon.py`:
- Uncomment the mirror worker startup block (lines 2254–2257).
- Worker task lifecycle (cancel + await in `stop()`) already handles `to_thread`
  cancellation correctly.

**Why**

Thread-level isolation prevents reconciliation I/O from starving the asyncio
event loop. `asyncio.to_thread` is the established codebase pattern (used in
`api_routes.py:66`, `monitoring_service.py:105`) and the minimum-invasive
approach that preserves the existing lifecycle model.

**Verification**

- Test: `_reconcile_sync` processes transcripts and returns correct counts.
- Test: second call returns `processed=0` (convergence).
- Operational: API watch loop-lag warnings disappear during reconciliation.
- Test: daemon shutdown cancels the mirror worker cleanly.

**Referenced files**

- `teleclaude/mirrors/worker.py` (modify)
- `teleclaude/mirrors/generator.py` (modify)
- `teleclaude/daemon.py` (modify)
- `tests/unit/test_mirror_worker.py` (extend)

---

### Task A4: Re-enable event-driven mirror dispatch

**What**

Remove the early-return guards in:
- `teleclaude/mirrors/event_handlers.py` `_dispatch()` (line 18: `return`).
- Verify `register_default_processors()` is called during daemon startup
  (already wired at `daemon.py:363` — no code change needed, verification only).

The event handlers (`handle_agent_stop`, `handle_session_closed`) dispatch mirror
generation for individual sessions as they close. This is the real-time path —
fast (single transcript) and acceptable in the event loop.

**Why**

The early-return was a safety measure during the hang investigation. With bulk
reconciliation now in a thread (A3), individual event-driven mirror generation
is safe. Both paths must be active: events for real-time, worker for catch-up.

**Verification**

- Un-skip `test_dispatch_isolates_processor_failures`.
- All mirror processor tests pass.
- Verify `register_default_processors()` is wired in event system setup.

**Referenced files**

- `teleclaude/mirrors/event_handlers.py` (modify)
- `tests/unit/test_mirror_processors.py` (modify — un-skip)

---

### Task A5: Reconciliation metrics and measurement gate

**What**

After each `_reconcile_sync` run, emit structured log metrics:

```
mirror.reconciliation.complete discovered=N processed=N skipped_unchanged=N skipped_no_context=N duration_s=N.N wal_before_kb=N wal_after_kb=N
```

WAL size measured by reading `{db_path}-wal` stat before and after the sync run.

**Measurement gate criteria** (addresses review Finding 3):

The gate passes when all four conditions hold over 3+ consecutive reconciliation
cycles after initial stabilization:

1. **Convergence:** `processed` count is <5% of `discovered` in steady state.
2. **WAL pressure:** `wal_after_kb - wal_before_kb` < 100 KB per cycle.
3. **Loop lag:** zero `API watch: loop lag` warnings during reconciliation
   (checked via `instrukt-ai-logs teleclaude --grep "API watch: loop lag"`).
4. **Endpoint latency:** zero `API watch: slow requests` warnings for
   `/sessions`, `/health`, `/computers` during reconciliation.

If any condition fails after 3 cycles, the DB split (A6) is triggered.

**Why**

The DB split decision must be data-driven (requirements + review Finding 3).
Concrete thresholds make the gate mechanically verifiable and prevent both
premature optimization and deferred action.

**Verification**

- Test: `_reconcile_sync` returns `ReconcileResult` with all fields populated.
- Test: log output contains structured metric fields.
- After deployment: `instrukt-ai-logs teleclaude --grep mirror.reconciliation`
  shows the metrics.

**Referenced files**

- `teleclaude/mirrors/worker.py` (modify)
- `tests/unit/test_mirror_worker.py` (extend)

---

### Task A6: Conditional DB split (gate-triggered only)

**What**

*Only if A5 measurement gate fails.* Move mirror storage to a separate SQLite
database.

**Config surface** (addresses review Finding 2):
- New config key: `database.mirrors_path` (string, optional).
- Default: empty (uses `database.path` — current behavior).
- When set: all mirror store operations route to this separate DB.
- `config.sample.yml`: add `mirrors_path: ""` under `database:` section with
  comment explaining when to set it.
- Config wizard: expose under database settings group.

Code changes:
- `teleclaude/mirrors/store.py` `resolve_db_path`: check `config.database.mirrors_path`
  first, fall back to `config.database.path`.
- New migration to create mirrors table + FTS + triggers in the separate DB.
- Daemon startup: run mirror migrations on the mirror DB if configured.
- Add WAL checkpoint for the mirror DB in the existing checkpoint loop.

**Why**

If same-DB write contention persists after canonical pruning and process
isolation, storage separation is the only remaining lever. The config key
makes this reversible — remove the path to revert to single-DB.

**Verification**

- If triggered: tests use separate DB path, mirror ops work independently.
- Config wizard shows the new setting.
- `config.sample.yml` documents the key.
- If not triggered: this task is skipped and documented as deferred.

**Referenced files (conditional)**

- `teleclaude/mirrors/store.py` (modify)
- `teleclaude/config/__init__.py` (modify)
- `config.sample.yml` (modify)
- `teleclaude/core/migrations/0XX_mirror_db_init.py` (create)
- `teleclaude/daemon.py` (modify)

---

## Lane B: Correctness

*Depends on Lane A measurement gate (A5) passing.*

### Task B1: Exact canonical source identity

**What**

Replace fallback `session_id` derivation in the worker with canonical-only identity.

Current behavior (`worker.py` lines 61–63):
```python
session_id = context.session_id if context else _fallback_session_id(...)
project = context.project if context else _fallback_project(...)
```

New behavior:
- If `get_session_context()` returns a context → use `context.session_id`.
- If no context → skip the transcript. Log at debug level with path and agent.
  Increment `skipped_no_context` counter in `ReconcileResult`.

Add `source_identity` column to mirrors table via migration:
- Value: `{agent}:{relative_transcript_path}` — deterministic and collision-safe.
- `UNIQUE` constraint on `source_identity`.
- Upsert `ON CONFLICT` changes from `session_id` to `source_identity`.
- `session_id` column preserved for API query compatibility but **UNIQUE dropped**.
  Rationale: with fallback identity removed, different transcripts that previously
  collided on truncated session_id now coexist. Keeping UNIQUE on session_id would
  cause insert failures for legitimate distinct mirrors.

Migration (table rebuild required — SQLite cannot drop constraints in-place):
1. Create `mirrors_new` with identical schema except `session_id` is
   `TEXT NOT NULL` (no UNIQUE) and `source_identity TEXT` is added.
2. Copy all rows from `mirrors` to `mirrors_new`.
3. Backfill `source_identity` from `metadata->transcript_path` for existing rows.
4. Drop old FTS triggers (`mirrors_ai`, `mirrors_ad`, `mirrors_au`).
5. Drop `mirrors_fts` virtual table.
6. Drop `mirrors` table.
7. Rename `mirrors_new` to `mirrors`.
8. Recreate indexes (`idx_mirrors_agent`, `idx_mirrors_project`,
   `idx_mirrors_timestamp`) + new `UNIQUE` index on `source_identity`
   (ignoring NULLs for pre-backfill rows).
9. Recreate `mirrors_fts` and all three triggers.

Store operation alignment — two call paths, two identity keys:

- **Worker path** (reconciliation): operates by `source_identity` for upsert,
  get, and delete. The worker always has `source_identity` because it constructs
  it from the transcript path.
- **Event-driven path** (real-time): operates by `session_id` for all store ops.
  Event handlers receive `session_id` from context and don't construct
  `source_identity`. This path remains unchanged.

Store changes:
- `upsert_mirror`: add `source_identity` field to `MirrorRecord`. Worker sets it;
  event-driven callers set it to `None`. Upsert uses `ON CONFLICT(source_identity)`
  when `source_identity` is set, `ON CONFLICT DO NOTHING` when it's `None`
  (event path — existing row wins if present).
- `get_mirror`: add optional `source_identity` param. When provided, query by
  `source_identity` instead of `session_id`.
- `delete_mirror`: add optional `source_identity` param. When provided, delete
  by `source_identity` instead of `session_id`.

**Why**

Path-derived session IDs are lossy (truncated to 12 chars, ambiguous across
agents). This causes collisions where different sessions overwrite each other.
Canonical identity from the sessions table is authoritative. The dual-key
approach preserves the event-driven path (which has authoritative session_id
from the sessions table) while giving the worker a collision-safe key.

**Verification**

- Test: worker skips candidates without session context (no fallback calls).
- Test: `processed` excludes skipped candidates.
- Test: upsert with same `source_identity` updates, not inserts.
- Test: `get_mirror(source_identity=...)` returns correct record.
- Test: `delete_mirror(source_identity=...)` deletes correct record.
- Test: event-driven path upsert still works with `source_identity=None`.
- Test: migration up/down is reversible (including table rebuild).

**Referenced files**

- `teleclaude/mirrors/worker.py` (modify)
- `teleclaude/mirrors/store.py` (modify — upsert, get, delete gain source_identity)
- `teleclaude/mirrors/generator.py` (modify)
- `teleclaude/core/migrations/0XX_mirror_source_identity.py` (create)
- `tests/unit/test_mirror_worker.py` (extend)
- `tests/unit/test_mirror_store.py` (create — store operation tests for dual-key)

---

### Task B2: Durable skip/tombstone state for empty transcripts

**What**

Add `mirror_tombstones` table:

```sql
CREATE TABLE mirror_tombstones (
    source_identity TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    transcript_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    file_mtime TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

Worker logic:
- Before processing, check tombstone for the transcript's `source_identity`.
- If tombstone exists AND `file_size` + `file_mtime` match → skip.
- If tombstone exists but file changed → delete tombstone, reprocess.
- If `generate_mirror_sync` finds no messages → insert tombstone, delete mirror
  (worker path: delete by `source_identity`).
- If transcript has messages but tombstone exists → delete tombstone (file gained content).

**Why**

Empty transcripts churn forever: each cycle deletes and re-evaluates them.
Tombstones let reconciliation converge to near-zero `processed` in steady state,
satisfying the convergence invariant.

**Verification**

- Test: empty transcript tombstoned after first pass; second pass skips it.
- Test: modified file (changed mtime/size) clears tombstone, triggers reprocess.
- Test: tombstone does not prevent processing of non-empty transcripts.
- Test: transcript that gains content removes its tombstone.

**Referenced files**

- `teleclaude/core/migrations/0XX_add_mirror_tombstones.py` (create)
- `teleclaude/mirrors/store.py` (add tombstone CRUD)
- `teleclaude/mirrors/worker.py` (check tombstones before processing)
- `teleclaude/mirrors/generator.py` (create tombstone on empty result)
- `tests/unit/test_mirror_worker.py` (extend)

---

### Task B3: Canonical-only backfill and convergence closeout

**What**

After B1 and B2 are stable, run a one-time cleanup + backfill:

1. Delete mirror rows where `source_identity IS NULL` (pre-migration orphans).
2. Delete mirror rows whose `metadata->transcript_path` fails `is_canonical`.
3. Run one full reconciliation cycle to populate `source_identity` for all
   canonical transcripts with session context.
4. Log cleanup and backfill counts.

Can be triggered as a flag on the worker (`MirrorWorker.backfill_sync()`) or
invoked manually from daemon startup with a one-time gate.

**Why**

After identity model changes, existing mirrors may have stale path-derived IDs.
Backfill rewrites them with canonical IDs. Without it, search results contain
duplicates or stale entries.

**Verification**

- Test: backfill removes orphan/non-canonical rows.
- Test: subsequent reconciliation cycles show `processed` near zero.
- After running: mirror count ≤ canonical session count.

**Referenced files**

- `teleclaude/mirrors/worker.py` (add `backfill_sync` method)
- `tests/unit/test_mirror_worker.py` (extend)

---

## Separate Dependent Workstream

### Task D1: `/todos/integrate` receipt-backing tracked separately

**What**

Track `/todos/integrate` receipt-backing as a separate roadmap entry. Do not
bundle into mirror code changes.

**Why**

Keeps mirror incident containment independent from workflow API migration risk.

**Verification**

- Separate roadmap entry exists and is linked as dependent work.

**Referenced files**

- `todos/roadmap.yaml`

---

## Task Dependency Graph

```
A1 (allowlist) ─── A2 (prune) ──┐
                                 │
A3 (thread iso) ─────────────────┼── A5 (metrics/gate) ── A6 (conditional DB split)
                                 │         │
A4 (re-enable dispatch) ─────────┘         │
                                           ├── B1 (identity)
                                           ├── B2 (tombstones)
                                           └── B3 (backfill, depends on B1+B2)
```

A1, A3, and A4 are independent — can be built in parallel.
A2 depends on A1 (needs `is_canonical`).
A5 depends on A1+A2+A3+A4 all landing.
A6 is conditional on A5 gate failing.
B1, B2 depend on A5 gate passing.
B3 depends on B1+B2.

---

## Validation

### Targeted tests

- [ ] `pytest tests/unit/test_transcript_discovery.py`
- [ ] `pytest tests/unit/test_mirror_worker.py`
- [ ] `pytest tests/unit/test_mirror_generator.py`
- [ ] `pytest tests/unit/test_mirror_processors.py`
- [ ] `pytest tests/unit/test_mirror_store.py`
- [ ] `pytest tests/unit/test_mirror_prune_migration.py`
- [ ] `pytest tests/unit/test_history_mirror_search.py`
- [ ] `pytest tests/unit/test_mirror_api_routes.py`

### Quality checks

- [ ] `make lint`
- [ ] `make status`

## Review Readiness

- [ ] Lane A proof obligations satisfied before Lane B begins.
- [ ] DB split decision evidence-backed with concrete thresholds (Finding 3).
- [ ] Conditional config surface documented (Finding 2).
- [ ] `/todos/integrate` receipt migration tracked separately (D1).
- [ ] All implemented checklist items marked `[x]`.
