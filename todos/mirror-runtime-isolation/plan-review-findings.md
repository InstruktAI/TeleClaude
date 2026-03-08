# Plan Review Findings: mirror-runtime-isolation

## Requirement Coverage

All seven success criteria from `requirements.md` map to plan tasks:

| Requirement | Plan Task(s) |
|---|---|
| Discovery invariant | A1 (allowlist), A2 (prune) |
| Identity invariant | B1 (canonical source identity) |
| Runtime isolation invariant | A3 (thread isolation) |
| Convergence invariant | A5 (metrics), B2 (tombstones) |
| Empty-transcript invariant | B2 (tombstones) |
| Storage decision invariant | A5 (gate), A6 (conditional split) |
| Workflow boundary invariant | D1 (separate tracking) |

No orphan requirements. No orphan tasks (D1 traces to out-of-scope boundary).

## Findings

### Important

**1. B1: `session_id` UNIQUE constraint interaction unspecified**

The existing `mirrors` table has `session_id TEXT NOT NULL UNIQUE` (migration 026).
The plan adds `source_identity TEXT UNIQUE` and changes upsert from
`ON CONFLICT(session_id)` to `ON CONFLICT(source_identity)`.

The plan doesn't address what happens to the `session_id` UNIQUE constraint.
Two scenarios need resolution:

- **Keep UNIQUE on session_id:** The plan says transcripts without context are
  skipped, so session_id always comes from the authoritative sessions table.
  If 1:1 transcript-to-session is guaranteed, UNIQUE on both columns is safe.
  The plan should state this assumption explicitly.
- **Drop UNIQUE on session_id:** SQLite can't `ALTER TABLE ... DROP CONSTRAINT`.
  This requires a table rebuild (CREATE new → COPY → DROP old → RENAME →
  recreate indexes, FTS, and triggers). The migration task must include these
  steps if this path is chosen.

The builder needs clarity on which path to take before starting B1.

**2. B1/B2: Store operations not aligned for dual identity model**

After B1, the worker upserts by `source_identity`. But `get_mirror()` and
`delete_mirror()` in `store.py` still operate by `session_id`.

Two call paths exist:
- **Event-driven** (A4): receives `session_id` from context, calls
  `generate_mirror(session_id=...)` which calls `delete_mirror(session_id)`.
- **Worker** (A3/B1): has `source_identity`, uses it for upsert but needs
  to delete mirrors for empty transcripts (B2) — which `delete_mirror` key?

The plan should specify:
- Whether `delete_mirror` and `get_mirror` gain a `source_identity` parameter.
- Which key each call path uses for each store operation.
- Whether the event-driven path continues using `session_id` for all operations.

### Suggestions

**1. A3: Title accuracy**

Task is titled "Process-isolated reconciliation worker" but uses
`asyncio.to_thread()` (thread, not process). The plan body is accurate;
consider aligning the title to "Thread-isolated reconciliation worker."

**2. A4: `register_default_processors()` already wired**

The plan says "Ensure `register_default_processors()` is called during daemon
startup." This is already done (`daemon.py:363`). Marking as verification-only
(no code change needed) would prevent the builder from searching for missing
wiring.

## Verdict

**APPROVE** — The plan is well-grounded, covers all requirements, has rationale
and verification for every task, and the dependency graph is sound. The two
Important findings are localized to B1 migration details and store alignment.
They don't require structural rework — the builder can resolve them during B1
implementation by clarifying the constraint strategy and adding store operations
for the new identity key.
