# DOR Report: notification-service

## Assessment Summary

**Draft phase** — artifacts refined from brain dump (`input.md`) into structured requirements
and implementation plan. The gate phase will make the formal readiness decision.

## Gate Analysis

### 1. Intent & Success ✅

The problem statement is clear: TeleClaude has no unified notification system. Autonomous events
are lost or go through bespoke paths. The intended outcome is explicit: a schema-driven event
processor backed by Redis Streams and SQLite, with API and WebSocket delivery.

Success criteria are concrete and testable (package imports, API responses, test suite, lint).

### 2. Scope & Size ⚠️

**This is the primary concern.** The requirements scope is well-defined but the implementation
plan has 8 phases with ~20 tasks. This is substantial for a single AI session:

- New package structure with its own DB, migration, and connection management
- Redis Streams consumer group (new pattern for this codebase)
- Full notification processor with schema-driven routing
- 6+ HTTP API endpoints
- WebSocket push integration
- 13+ event schema definitions
- Old system removal and call site rewiring
- Test suite

**Recommendation for gate:** Evaluate whether to split into two or three dependent todos:

1. `notification-service-core` — package, envelope, storage, processor, API (Phases 1-4)
2. `notification-service-integration` — daemon hosting, producers, CLI, consolidation (Phases 5-6)
3. Or keep as one if the builder can work incrementally with commits per phase.

The phased implementation plan is designed for incremental progress — each phase is testable
independently. A skilled builder could commit after each phase and resume if context limits hit.

### 3. Verification ✅

Clear verification path:

- Unit tests for each component (envelope, catalog, DB, state machine)
- Integration test for the full pipeline (producer → stream → processor → SQLite → API)
- `make test` and `make lint` as quality gates
- Demo script validates the deployed system

### 4. Approach Known ✅

The technical path is well-defined:

- Redis Streams: pattern exists in the codebase (`redis_transport.py` uses XADD/XREAD)
- SQLite with aiosqlite: established pattern in `core/db.py`
- Pydantic models: established pattern in `api_models.py`
- FastAPI endpoints: established pattern in `api_server.py`
- WebSocket push: established pattern in `api_server.py`
- Background task lifecycle: established pattern in `daemon.py`

Consumer groups (`XREADGROUP`, `XACK`) are new to this codebase but well-documented by Redis.

### 5. Research Complete ✅

No new third-party dependencies required:

- Redis Streams: already using redis-py async client
- SQLite: already using aiosqlite
- Pydantic: already a core dependency
- FastAPI: already the API framework

Redis Streams consumer group semantics (XGROUP CREATE, XREADGROUP, XACK, pending entries)
are well-documented in Redis official docs. No research spike needed.

### 6. Dependencies & Preconditions ✅

- Redis is already running and configured
- The daemon's FastAPI server is already running
- WebSocket infrastructure exists
- No new config keys required (notification DB path can default to `~/.teleclaude/notifications.db`)
- The old notification system has identified call sites (daemon.py, db.py)

### 7. Integration Safety ✅

- New package is additive — no existing code changes until Phase 6 (consolidation)
- Consolidation (old system removal) is the last phase, after the new system is proven
- The old and new systems can coexist during development
- Rollback: revert the consolidation phase to restore old system if needed

### 8. Tooling Impact ✅

- New `telec events list` CLI command — requires CLI registration
- No changes to existing scaffolding procedures
- `pyproject.toml` needs the new package registered

## Open Questions

1. **Package structure**: should `teleclaude_notifications/` be a top-level sibling to `teleclaude/`
   or a separate installable package? The requirements say sibling directory. Confirm with the
   codebase's packaging setup.
2. **Redis Stream name**: `teleclaude:notifications` — is there a naming convention for Redis
   keys in this codebase?
3. **Notification DB path**: `~/.teleclaude/notifications.db` as default — confirm this aligns
   with the daemon's data directory conventions.
4. **Existing Telegram admin alerts**: the old notification system delivers alerts via Telegram.
   The requirements say to wire this through the new service as a delivery adapter. Confirm
   this is in scope or deferred.

## Assumptions

- The separate SQLite database does NOT violate the single-database policy. That policy governs
  the daemon's data; this is a separate service's data (per `input.md` design rationale).
- The notification processor runs as a background task in the daemon process (not a separate
  process). This is consistent with how other workers run (webhook delivery, resource monitor).
- The wire format between Redis and the processor is JSON (serialized envelope).
- Consumer group `notification-processor` with one consumer per daemon instance is sufficient
  for the expected event volume (hundreds per day).

## Draft Assessment

| Gate               | Status                     |
| ------------------ | -------------------------- |
| Intent & success   | Pass                       |
| Scope & size       | Warning — large but phased |
| Verification       | Pass                       |
| Approach known     | Pass                       |
| Research complete  | Pass                       |
| Dependencies       | Pass                       |
| Integration safety | Pass                       |
| Tooling impact     | Pass                       |

**Draft verdict:** The todo is well-defined and technically sound. The primary question for the
gate is scope sizing — whether this should ship as one todo or be split. The phased plan
mitigates scope risk by allowing incremental progress with commits per phase.
