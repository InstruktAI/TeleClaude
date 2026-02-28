# DOR Gate Report: event-platform-core

**Gate date:** 2026-02-28
**Verdict:** needs_work
**Score:** 7/10

## Gate Summary

Seven of eight DOR gates pass. One plan-to-requirement contradiction blocks passage.
The fix is localized — a single section of the implementation plan must be reconciled
with the requirements. No structural issues with scope, verification, or dependencies.

## Gate Results

### 1. Intent & success — PASS

Problem statement and outcome are explicit. The `input.md` references the parent
`event-platform` vision and scopes Phase 1 clearly. Requirements list 18 numbered
scope items and 16 concrete success criteria. What and why are captured.

### 2. Scope & size — PASS (with note)

22 tasks across 8 phases is large. The plan mitigates this through phased commits —
the builder commits after each phase and can resume in a new session. Cross-cutting
changes (daemon.py, api_server.py, new package, old package removal) are explicitly
called out and justified. Consolidation is correctly placed last (Phase 6) after all
new code is proven.

### 3. Verification — PASS

Success criteria are concrete and machine-checkable:

- Import checks (`python -c "from teleclaude_events import ..."`)
- Boundary checks (`grep -r "from teleclaude\." teleclaude_events/`)
- API checks (curl endpoints)
- Test/lint gates (`make test`, `make lint`)
- Demo.md has executable validation blocks covering all major features.

### 4. Approach known — PASS

All referenced codebase patterns verified:

- Redis Streams XADD: `redis_transport.py:1734` confirmed
- Redis Streams XREADGROUP: **already exists** in `teleclaude/channels/consumer.py`
  (the risk assessment says "XREADGROUP is new" — this is overstated; the channels
  module already uses `xreadgroup` with `ensure_consumer_group`)
- aiosqlite DB: `teleclaude/core/db.py` confirmed
- FastAPI endpoints: `teleclaude/api_server.py` confirmed
- WebSocket subscriptions: `api_server.py:223` confirmed
- Background task hosting: `daemon.py:1857` (NotificationOutboxWorker) confirmed
- Telegram delivery: `teleclaude/notifications/telegram.py` confirmed

### 5. Research complete — PASS (auto-satisfied)

No new third-party dependencies. Redis-py async, aiosqlite, Pydantic, FastAPI all
already in use. Consumer group pattern already implemented in channels module.

### 6. Dependencies & preconditions — PASS

- `pyproject.toml` include pattern `["teleclaude*"]` matches `teleclaude_events*` (plan
  correctly notes to verify)
- Redis: already running
- Roadmap dependencies correct: event-platform-core depends on event-platform (holder),
  unblocks 7 downstream todos
- No new configs, env vars, or external systems required

### 7. Integration safety — PASS

Phased delivery with commits between phases. Consolidation (removing old notifications
package) is Phase 6 — last before tests. The plan includes audit steps:

- grep for all old call sites
- migration to drop old table
- verify old imports removed

Rollback: revert the consolidation commit if breakage occurs. Earlier phases are additive.

### 8. Tooling impact — PASS (auto-satisfied)

No tooling or scaffolding changes.

## Plan-to-Requirement Fidelity

All 18 requirements trace to implementation tasks. One contradiction found:

### BLOCKER: Dedup cartridge behavior contradiction

**Requirement 6** states:

> Deduplication cartridge: checks idempotency key derived from schema-declared payload
> fields. **Drops duplicates (returns None).** First cartridge in the chain.

**Implementation plan Task 3.2** states:

> If key exists: set `event.idempotency_key` and return event (let projector handle upsert).
> **Dedup is advisory — it sets the key.** The projector uses the key for upsert.

**Demo.md Step 6** shows drop behavior:

> Emit the same event twice... only one notification exists. **The dedup cartridge dropped
> the duplicate.**

Three artifacts, two conflicting behaviors:

- Requirements + demo: dedup drops duplicates (returns None)
- Implementation plan: dedup is advisory, passes events through, projector upserts

These are functionally different. A drop-based dedup means duplicate events never reach
the projector — the notification row is never touched again. An advisory dedup means
duplicate events flow through to the projector which upserts — the notification row gets
touched but content is unchanged.

**Resolution needed:** Either:

1. Update the implementation plan to match the requirements (dedup checks DB or in-memory
   set, drops true duplicates), or
2. Update the requirements to reflect the advisory approach (dedup tags, projector upserts)
   and update the demo accordingly.

Both approaches are valid. The advisory approach is arguably simpler (dedup doesn't need
DB access) but the requirements explicitly specify drop behavior.

## Observations (non-blocking)

1. **XREADGROUP risk overstated:** The risk section says "XREADGROUP is new: codebase
   uses XREAD only." This is incorrect — `teleclaude/channels/consumer.py` already
   implements `xreadgroup` with `ensure_consumer_group`. The builder should reference
   this existing pattern directly.

2. **`pipeline_state` table:** Task 2.2 creates a `pipeline_state` key-value table for
   "consumer group last-processed tracking." XREADGROUP handles its own position tracking
   via the consumer group. The table may be useful for other pipeline state, but the
   stated purpose is redundant. Minor — builder can decide.

3. **Email delivery in consolidation:** The old `teleclaude/notifications/email.py` exists.
   Phase 6 removes the entire directory. The audit step (grep for call sites) should catch
   email.py references, but it's worth the builder being aware during consolidation.

## Requirement-to-Task Mapping

| #   | Requirement                | Task(s)  | Status              |
| --- | -------------------------- | -------- | ------------------- |
| 1   | Separate package           | 1.1      | OK                  |
| 2   | Five-layer envelope        | 1.2      | OK                  |
| 3   | Event catalog              | 1.3      | OK                  |
| 4   | Redis Streams producer     | 3.6      | OK                  |
| 5   | Pipeline runtime           | 3.1, 3.4 | OK                  |
| 6   | Deduplication cartridge    | 3.2      | **CONTRADICTION**   |
| 7   | Notification projector     | 3.3      | OK                  |
| 8   | Separate SQLite DB         | 2.1, 2.2 | OK                  |
| 9   | Notification state machine | 2.2      | OK                  |
| 10  | HTTP API                   | 4.1      | OK                  |
| 11  | WebSocket push             | 4.2      | OK                  |
| 12  | Daemon hosting             | 5.1      | OK                  |
| 13  | Telegram delivery adapter  | 5.3      | OK                  |
| 14  | Initial event schemas      | 5.4      | OK                  |
| 15  | First producers wired      | 5.2      | OK                  |
| 16  | telec events list CLI      | 5.5      | OK                  |
| 17  | Idempotency                | 3.2      | OK (key derivation) |
| 18  | Consolidation              | 6.1      | OK                  |
