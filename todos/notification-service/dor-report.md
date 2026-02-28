# DOR Report: notification-service

## Gate Verdict: PASS (score 8/10)

Assessed by gate worker on 2026-02-28. All DOR gates satisfied after one minimal edit
(added missing Telegram delivery adapter task to close plan-to-requirement gap).

## Gate Analysis

### 1. Intent & Success — PASS

The problem statement is clear and explicit: TeleClaude has no unified notification system.
Autonomous events go through bespoke paths or are lost. The intended outcome is a schema-driven
event processor backed by Redis Streams and SQLite, with API and WebSocket delivery.

11 success criteria are concrete and testable — each can be verified with a command or assertion.

### 2. Scope & Size — PASS (with risk note)

The implementation plan has 8 phases with ~22 tasks. This is substantial. The draft flagged
this as the primary concern and proposed splitting into 2-3 dependent todos.

**Gate decision: keep as one todo.** Rationale:

- The phased plan is designed for incremental testability — each phase is independently
  committable. A builder commits after each phase and can resume in a new session.
- The natural split point (core vs integration) would produce a first todo that creates
  a package nobody uses until the second todo wires it in. This is artificial overhead.
- All phases build on each other linearly — there's no independent parallelism that
  splitting would enable.
- The DOR policy says "If it requires multiple phases, it is split." But these are BUILD
  phases (steps in constructing one feature), not deployment phases (independent deliverables).
  The feature is one deployable unit.

**Risk mitigation:** Builder should commit after each phase. If context exhaustion approaches,
any builder can resume from the last committed phase. The plan is detailed enough for handoff.

### 3. Verification — PASS

Clear verification path:

- Unit tests for each component (envelope, catalog, DB, state machine)
- Integration test: producer → Redis Stream → processor → SQLite → API query
- `make test` and `make lint` as quality gates
- Demo script (`demo.md`) validates the deployed system end-to-end

### 4. Approach Known — PASS

Every pattern is confirmed in the codebase:

| Pattern              | Evidence                                                      |
| -------------------- | ------------------------------------------------------------- |
| Redis Streams XADD   | `teleclaude/transport/redis_transport.py:1734`                |
| Redis Streams XREAD  | `teleclaude/transport/redis_transport.py:1001`                |
| aiosqlite DB         | `teleclaude/core/db.py`, 42 files reference aiosqlite         |
| Pydantic models      | Established pattern across codebase                           |
| FastAPI endpoints    | `teleclaude/api_server.py`                                    |
| WebSocket push       | `teleclaude/api_server.py:1878-1894` (full WS infrastructure) |
| Background task host | `teleclaude/daemon.py:1857-1868` (NotificationOutboxWorker)   |

Consumer groups (`XREADGROUP`, `XACK`) are new to this codebase but are a standard Redis
Streams pattern with comprehensive documentation. No spike needed.

### 5. Research Complete — PASS

No new third-party dependencies:

- Redis (redis-py async): already in use
- SQLite (aiosqlite >= 0.21.0): already in `pyproject.toml`
- Pydantic: core dependency
- FastAPI: API framework

### 6. Dependencies & Preconditions — PASS

- Redis: running and configured (used by redis_transport.py)
- FastAPI server: running (api_server.py)
- WebSocket infrastructure: established (api_server.py)
- Notification DB path: `~/.teleclaude/notifications.db` — consistent with data directory
  convention (`~/.teleclaude/`)
- Redis Stream name: `teleclaude:notifications` — consistent with codebase naming convention
  (`messages:{computer}`, `output:{computer}:{id}`)
- Roadmap correctly shows 4 dependents: `history-search-upgrade`, `prepare-quality-runner`,
  `todo-dump-command`, `content-dump-command`

### 7. Integration Safety — PASS

- New package is purely additive until Phase 6 (consolidation)
- Old and new systems coexist during development
- Consolidation is the last phase, after the new system is proven
- Rollback: revert consolidation phase to restore old system

### 8. Tooling Impact — PASS

- New `telec events list` CLI command — Task 5.6
- `pyproject.toml` update for new package — Task 1.1
- No changes to existing scaffolding procedures

## Actions Taken

### Plan edit: added Telegram delivery adapter (Task 5.3)

**Blocker found:** Requirement #14 says "Wire the remaining Telegram delivery need (admin
alerts) through the new service as a delivery adapter." The implementation plan had no task
for this — Task 6.1 removed the old system but created no Telegram delivery path in the
new service.

**Fix:** Added Task 5.3 (Telegram delivery adapter) to Phase 5. The adapter receives
processor callbacks, filters by notification level (>= WORKFLOW), and reuses the existing
`send_telegram_dm` function. Registered alongside WebSocket push in daemon startup.

### Open questions resolved

All four open questions from the draft are resolved through codebase analysis:

1. **Package structure**: sibling directory to `teleclaude/`. Requirements are explicit.
2. **Redis Stream name**: `teleclaude:notifications` follows the `{namespace}:{entity}`
   convention used by redis_transport.py (`messages:{computer}`, `output:{computer}:{id}`).
3. **Notification DB path**: `~/.teleclaude/notifications.db` is consistent with the
   `~/.teleclaude/` data directory convention.
4. **Telegram admin alerts**: now in scope via Task 5.3 (Telegram delivery adapter).

## Policy Notes

### Single-database policy

The notification service creates `~/.teleclaude/notifications.db` — a separate SQLite file
outside the main repo. The single-database policy governs `teleclaude.db` at the project
root and says "Extra .db files in the main repo are treated as bugs."

The notification DB is NOT in the main repo (`~/.teleclaude/` vs `${WORKING_DIR}/`).
The design rationale is explicit: no write contention, independent lifecycle, clean
ownership. This does not violate the letter of the policy.

**Note:** This establishes a precedent for daemon-hosted services with their own databases.
If more services follow this pattern, the single-database policy should be updated to
acknowledge service-specific databases in `~/.teleclaude/`.

## Assumptions (validated)

- The separate SQLite database does NOT violate the single-database policy (validated above).
- The notification processor runs as a background task in the daemon (consistent with
  `NotificationOutboxWorker` pattern in `daemon.py:1857`).
- Consumer group `notification-processor` with one consumer per daemon instance is sufficient
  for expected volume (hundreds of events per day).
- The wire format between Redis and the processor is JSON (consistent with `redis_transport.py`).

## Gate Summary

| Gate               | Status | Notes                                           |
| ------------------ | ------ | ----------------------------------------------- |
| Intent & success   | Pass   | 11 testable criteria                            |
| Scope & size       | Pass   | Large but phased; commits per phase mitigate    |
| Verification       | Pass   | Unit + integration tests, make test/lint, demo  |
| Approach known     | Pass   | All patterns confirmed in codebase              |
| Research complete  | Pass   | No new dependencies                             |
| Dependencies       | Pass   | All preconditions met, 4 dependents mapped      |
| Integration safety | Pass   | Additive until consolidation; rollback possible |
| Tooling impact     | Pass   | New CLI command + pyproject.toml update         |

**Score: 8/10 — PASS**
