# Review Findings: mirror-runtime-isolation

## Summary

All implementation-plan tasks are checked. The deferral of A6 (conditional DB split) is
justified — it depends on post-deployment A5 evidence that cannot be produced in-worktree.
The delivery is structurally sound: canonical allowlisting, source-identity migration,
thread-isolated reconciliation, tombstones, backfill, and structured metrics all land
correctly. Tests are comprehensive and pass (126 targeted, 3401 full suite per build notes).

Two Critical findings initially blocked APPROVE. Both were resolved in the fix pass,
along with all Important findings (I1–I5). I6 was investigated and accepted as-is.

---

## Critical

### C1. `_reconcile_sync` has no per-candidate error isolation

**File:** `teleclaude/mirrors/worker.py:108-166`

The reconciliation loop iterates over all discovered transcripts with no try/except around
the per-candidate body. If any single transcript causes an exception — `FileNotFoundError`
from a race between discovery and `stat()` (line 124), `PermissionError` on file read,
`sqlite3.IntegrityError` from upsert, or any error from `generate_mirror_sync` — the
entire reconciliation cycle aborts. All remaining transcripts are skipped and the
`ReconcileResult` counters are incomplete.

**Remediation:** Wrap the per-candidate body in try/except, log the error per-candidate,
and continue the loop. Track a `failed` counter in `ReconcileResult` for observability.

### C2. `MirrorWorker.run()` has no per-cycle error recovery

**File:** `teleclaude/mirrors/worker.py:209-214`

```python
async def run(self) -> None:
    await self.run_once()
    while True:
        await asyncio.sleep(self.interval_s)
        await self.run_once()
```

Any unhandled exception from `run_once()` propagates out of `run()` and permanently kills
the mirror worker task. The daemon's `_track_background_task` callback only logs the crash —
it does not restart the worker. Contrast with `maintenance_service.py:periodic_cleanup`
which wraps each cycle in try/except.

Transient errors (filesystem race, database lock timeout, corrupt transcript) will
permanently stop all mirror reconciliation for the daemon's lifetime.

**Remediation:** Wrap the loop body:
```python
async def run(self) -> None:
    while True:
        try:
            await self.run_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Mirror reconciliation cycle failed: %s", exc, exc_info=True)
        await asyncio.sleep(self.interval_s)
```

---

## Important

### I1. Migration 028 `down()` will crash on duplicate `session_id` rows

**File:** `teleclaude/core/migrations/028_add_mirror_source_identity.py:329-389`

The forward migration removes UNIQUE from `session_id` and adds UNIQUE to `source_identity`.
After the forward migration, multiple mirror rows with the same `session_id` but different
`source_identity` are legitimate. The `down()` migration copies all rows into
`_create_legacy_mirrors_table` which declares `session_id TEXT NOT NULL UNIQUE`. If duplicate
`session_id` values exist at rollback time, `executemany` will fail with a UNIQUE constraint
violation.

**Remediation:** Use `INSERT OR REPLACE` or deduplicate rows by `session_id` (keeping most
recent `updated_at`) in the `down()` path.

### I2. `generate_mirror` async wrapper blocks the event loop

**File:** `teleclaude/mirrors/generator.py:95-113`

The `async def generate_mirror()` calls `generate_mirror_sync()` directly without
`asyncio.to_thread()`. This performs blocking file I/O (transcript parsing) and blocking
SQLite writes on the event loop. While the plan acknowledges single-transcript event-driven
generation as "acceptable in the event loop," a large transcript could still block
noticeably. The `api_routes.py` uses `to_thread` for the same store operations.

**Remediation:** Either wrap with `asyncio.to_thread` for consistency with other mirror
API patterns, or add a code comment justifying the blocking call with a size expectation.

### I3. `build_source_identity` has no direct test coverage

**File:** `teleclaude/utils/transcript_discovery.py:52-61`

This function is the deterministic key for the entire source-identity deduplication model.
It is exercised indirectly through worker and processor tests, but the fallback path
(line 61 — path matches no discovery root, returns absolute path) is never tested. If
`_discovery_roots` changes, no test will directly catch identity key drift.

**Remediation:** Add a focused test for `build_source_identity` covering:
- Path under a discovery root → relative identity
- Path under Claude's second root (sessions dir) → relative identity
- Path matching no root → absolute fallback

### I4. `upsert_mirror` ValueError guard is untested

**File:** `teleclaude/mirrors/store.py:304-306`

The guard `if not record.source_identity: raise ValueError(...)` prevents insertion of
unkeyed mirror rows that would break deduplication. No test verifies this guard fires.

**Remediation:** Add a test that constructs a `MirrorRecord` with `source_identity=None`
and asserts `upsert_mirror` raises `ValueError`.

### I5. Stale docstring on `handle_session_closed`

**File:** `teleclaude/daemon.py:1136-1141`

The docstring says "This handler cleans up in-memory state only." After this delivery,
the handler also dispatches `handle_mirror_session_closed(ctx)` which performs database
writes. The claim is factually incorrect.

**Remediation:** Update the docstring to acknowledge mirror reconciliation dispatch.

### I6. Out-of-scope changes bundled in delivery

**Files:** `teleclaude/api_server.py`, `tests/unit/test_access_control.py`, `tests/unit/test_api_server.py`

The `human_role` preservation fix (commit `8bc86baf`) and the duplicate mock removal
(commit `5204a65f`) are independent fixes unrelated to mirror runtime isolation. While
they are correct and cleanly committed separately, they expand the delivery surface beyond
the requirements scope.

This is not blocking since the changes are independent and well-tested, but noted for
scope discipline.

---

## Suggestion

### S1. `get_mirror` ORDER BY clause is needlessly complex for source_identity queries

**File:** `teleclaude/mirrors/store.py:257-267`

When querying by `source_identity`, the `session_id`-based ORDER BY CASE expression is
dead code (all params are None, all CASE branches evaluate to ELSE 0). The ORDER BY could
be simplified or skipped when `source_identity` is the key.

### S2. `ReconcileResult` conflates tombstone skips with unchanged skips

**File:** `teleclaude/mirrors/worker.py:143-145`

When `_should_skip_tombstoned_transcript` returns True, the code increments
`skipped_unchanged`. This conflates two skip reasons: "mirror already up-to-date" vs
"tombstone still valid." A separate counter (e.g., `skipped_tombstoned`) would improve
metrics precision.

### S3. `generate_mirror` docstring is misleading

**File:** `teleclaude/mirrors/generator.py:104`

The docstring says "Async wrapper for mirror generation" but the function body calls
`generate_mirror_sync` synchronously. It is an `async def` that blocks. The docstring
should clarify this is an async-compatible entry point that does not offload to a thread.

### S4. `delete_mirror` silently returns when both keys are absent

**File:** `teleclaude/mirrors/store.py:378`

`if not session_id and not source_identity: return` — calling delete with no keys is a
programming error. A `ValueError` would be more appropriate than a silent no-op, consistent
with the `upsert_mirror` guard at line 304.

### S5. `daemon.py` double-getattr for config path

**File:** `teleclaude/daemon.py:2254`

`getattr(getattr(config, "database", None), "path", None)` — the daemon always has config
loaded. The original code used `config.database.path` directly. The double-getattr is
over-defensive; a simpler `config.database.path` with a standard AttributeError would be
clearer.

### S6. Test helper `_load_migration` duplicated across 4 files

**Files:** `tests/unit/test_mirror_worker.py`, `test_mirror_store.py`, `test_mirror_prune_migration.py`, `test_mirror_generator.py`

Identical helper copy-pasted in each file. A shared conftest fixture would reduce
maintenance cost.

### S7. Schema hand-crafting in API/search tests diverges from migration-based tests

**Files:** `tests/unit/test_mirror_api_routes.py`, `tests/unit/test_history_mirror_search.py`

These files define `_create_mirror_schema` with inline SQL rather than running actual
migrations. The worker and store tests correctly use migration files. The hand-crafted
schemas can drift from the real schema.

---

## Scope Verification

| Requirement | Implemented | Evidence |
|---|---|---|
| Canonical transcript allowlist | Yes | `is_canonical()` in `transcript_discovery.py`, applied in discovery + processors |
| Prune non-canonical mirrors | Yes | Migration 027, tested in `test_mirror_prune_migration.py` |
| Thread-isolated reconciliation | Yes | `_reconcile_sync` + `asyncio.to_thread` in `run_once` |
| Exact source identity | Yes | Migration 028, dual-key store ops, tested in `test_mirror_store.py` |
| Empty-transcript tombstones | Yes | Migration 029, tombstone logic in worker, tested |
| Structured completion metrics | Yes | `ReconcileResult` + structured log in `_log_reconcile_result` |
| Separate roadmap tracking (D1) | Yes | Entry in `todos/roadmap.yaml` |
| A6 DB split deferred | Yes | `deferrals.md` with justified trigger condition |

All requirements are met. No gold-plating in the mirror code itself.

## Deferrals Assessment

A6 deferral is justified. The gate requires 3+ production reconciliation cycles with
measurements — evidence that cannot be produced in a build worktree. The deferral trigger
is clear and mechanical.

## Demo Assessment

Two executable bash blocks that exercise 8 test files and 3 specific behavioral tests.
All test names verified as existing. Demo is adequate for a runtime-isolation delivery
where observable behavior requires a deployed daemon.

## Paradigm-Fit

- Data flow follows established store patterns
- `asyncio.to_thread` matches existing codebase convention (api_routes.py, monitoring_service.py)
- Migration structure follows existing migration patterns
- Test structure follows established patterns (real SQLite + actual migrations)

No paradigm violations.

## Security

No findings. All SQL is parameterized. No credentials in code. Log statements emit only
paths and counters. No injection surfaces.

## Fixes Applied

- **C1. `_reconcile_sync` has no per-candidate error isolation**
  Fixed by wrapping each candidate reconciliation body in `try/except`, logging the failing transcript, and adding a `failed` counter to `ReconcileResult` for cycle-level observability.
  Commit: `b7e27c9df`

- **C2. `MirrorWorker.run()` has no per-cycle error recovery**
  Fixed by wrapping each reconciliation cycle in `try/except`, preserving `CancelledError`, logging transient failures, and continuing the interval loop.
  Commit: `33e27c93f`

- **I1. Migration 028 `down()` will crash on duplicate `session_id` rows**
  Fixed by deduplicating rollback payloads by `session_id`, keeping the most recently updated row before rebuilding the legacy schema.
  Commit: `2dd608c2e`

- **I2. `generate_mirror` async wrapper blocks the event loop**
  Fixed by offloading `generate_mirror_sync()` with `asyncio.to_thread()` and adding direct wrapper coverage.
  Commit: `6754b9f7f`

- **I3. `build_source_identity` has no direct test coverage**
  Fixed by adding focused tests for project-root relative identity, Claude sessions-dir identity, and absolute-path fallback.
  Commit: `e58a9d40d`

- **I4. `upsert_mirror` ValueError guard is untested**
  Fixed by adding a store test that asserts `upsert_mirror()` rejects `MirrorRecord` values without `source_identity`.
  Commit: `57bd8da71`

- **I5. Stale docstring on `handle_session_closed`**
  Fixed by updating the docstring to reflect that the handler now dispatches mirror cleanup in addition to in-memory cleanup.
  Commit: `59dd56690`

- **I6. Out-of-scope changes bundled in delivery**
  Investigated by attempting to revert commits `5204a65f2` and `8bc86bafa`. The revert caused regressions in `tests/unit/test_api_server.py::test_send_message_direct_creates_link_and_routes_to_peers`, `tests/unit/test_access_control.py::test_create_session_unidentified_preserves_project`, and `tests/unit/test_access_control.py::test_create_session_api_without_identity_defaults_to_admin`, so no revert was applied.

---

## Verdict: APPROVE

All Critical and Important findings resolved. Suggestions S1–S7 remain open and are
non-blocking. The delivery is structurally sound with proper error isolation,
event-loop safety, migration rollback safety, and comprehensive test coverage
(3288 unit tests passing).
