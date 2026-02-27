# Implementation Plan: history-search-upgrade

## Overview

The upgrade replaces brute-force JSONL scanning with two layers: **generation** (daemon extracts conversation from transcripts into local SQLite via event-driven triggers + background safety net) and **search** (FTS5 queries in `history.py`, with live API calls for remote computers). Each computer stores only its own mirrors — no cross-computer replication. Remote search is on-the-fly via the daemon API.

Generation is event-driven first: AGENT_STOP fires after every agent turn (near-real-time), SESSION_CLOSED fires on session close (belt-and-suspenders). A background worker runs as a safety net, catching anything events missed. The worker's idempotent reconciliation IS the backfill — no separate backfill script.

## Phase 1: Storage Layer

### Task 1.1: Database migration — mirrors table + FTS5

**File(s):** `teleclaude/core/migrations/025_add_mirrors_table.py`

- [ ] Create `mirrors` table:
  ```sql
  CREATE TABLE IF NOT EXISTS mirrors (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL UNIQUE,
      computer TEXT NOT NULL,
      agent TEXT NOT NULL,
      project TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      timestamp_start TEXT,
      timestamp_end TEXT,
      conversation_text TEXT NOT NULL DEFAULT '',
      message_count INTEGER NOT NULL DEFAULT 0,
      metadata TEXT DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
  )
  ```
- [ ] Add indexes: `idx_mirrors_agent` on `(agent)`, `idx_mirrors_project` on `(project)`, `idx_mirrors_timestamp` on `(timestamp_start DESC)`
- [ ] Create `mirrors_fts` FTS5 virtual table: `USING fts5(title, conversation_text, content='mirrors', content_rowid='id')`
- [ ] Create triggers: `mirrors_ai` (after insert), `mirrors_ad` (after delete), `mirrors_au` (after update) — same pattern as `memory_obs_ai/ad/au` in migration 005
- [ ] Implement `async def down(db)` to drop FTS triggers, virtual table, indexes, and content table

The migration runner auto-discovers `*.py` files matching `^\d{3}_` in the migrations directory — no explicit registration needed.

---

## Phase 2: Generation Layer

### Task 2.1: Mirror generator module

**File(s):** `teleclaude/mirrors/__init__.py` (new), `teleclaude/mirrors/generator.py` (new)

- [ ] `async def generate_mirror(session_id: str, transcript_path: str, agent_name: AgentName, computer: str, project: str, db) -> None`
  - Calls `extract_structured_messages(transcript_path, agent_name, include_tools=False, include_thinking=False)` — returns `list[StructuredMessage]`
  - Strips `<system-reminder>...</system-reminder>` from user messages via `re.sub(r'<system-reminder>.*?</system-reminder>', '', text, flags=re.DOTALL).strip()`
  - Joins extracted messages into `conversation_text`
  - Writes to `mirrors` table via `INSERT OR REPLACE` by `session_id`
- [ ] Derive `title` from first user message (truncated), `timestamp_start`/`timestamp_end` from first/last message timestamps, `message_count` from count of extracted messages
- [ ] Handle edge cases: empty transcripts (skip), transcripts with only tool calls (skip — zero conversation messages)

### Task 2.2: Fan-out processor registry

**File(s):** `teleclaude/mirrors/processors.py` (new)

- [ ] Processor registry: list of async callables that accept event data
- [ ] `register_processor(fn)` / `get_processors()` interface
- [ ] Mirror generation processor: wraps `generate_mirror()` — resolves session_id to transcript path, extracts agent/computer/project, calls generator
- [ ] Registry is populated at daemon startup

### Task 2.3: AGENT_STOP event handler (primary trigger)

**File(s):** `teleclaude/mirrors/event_handlers.py` (new), wiring in agent_coordinator or daemon

- [ ] Hook into AGENT_STOP event path. AGENT_STOP is an `AgentHookEvents` value routed through `agent_coordinator.handle_event` (wired at daemon.py line 322 via `self.client.agent_event_handler`). The mirror handler runs after the coordinator finishes processing the event.
- [ ] On AGENT_STOP: extract session_id from event data, dispatch to all registered processors via the fan-out registry
- [ ] Mirror generation is async and non-blocking — errors are logged, not propagated to the event pipeline

### Task 2.4: SESSION_CLOSED event handler (secondary trigger)

**File(s):** `teleclaude/mirrors/event_handlers.py`, wiring in `teleclaude/daemon.py`

- [ ] Subscribe to `TeleClaudeEvents.SESSION_CLOSED` via `event_bus.subscribe()` — follows the daemon's name-based auto-discovery pattern (handler named `_handle_session_closed` is auto-wired) OR explicit subscription
- [ ] On SESSION_CLOSED: extract session_id from event data, dispatch to all registered processors via the fan-out registry
- [ ] This is belt-and-suspenders: ensures final mirror state when session ends, even if AGENT_STOP was missed

### Task 2.5: Background mirror worker (safety net)

**File(s):** `teleclaude/mirrors/worker.py` (new)

- [ ] Idempotent reconciliation loop (5-minute interval):
  1. Discovers transcript files across all agents using `AGENT_PROTOCOL` from `teleclaude.constants` (session_dir + log_pattern per agent)
  2. Compares file mtime against `mirrors.updated_at` to find sessions needing regeneration
  3. Calls `generate_mirror()` for each stale/new transcript
- [ ] First run on a fresh install: processes ALL existing transcripts (IS the backfill). Same code path as subsequent runs.
- [ ] Runs on daemon startup as initial sweep, then periodically every 5 minutes
- [ ] Progress logging: logs counts (e.g., "Mirror reconciliation: 0/3660", "1200/3660", "complete in 4m 12s"). When notification-service is available, reports through notification API instead.
- [ ] Graceful shutdown via cancellation token

### Task 2.6: Wire into daemon startup/shutdown

**File(s):** `teleclaude/daemon.py`

- [ ] Start mirror worker as background task in `start()` using `asyncio.create_task()`, track via `_track_background_task(task, "mirror-worker")`
- [ ] Register AGENT_STOP handler in agent_coordinator event path
- [ ] Register SESSION_CLOSED handler via event bus
- [ ] Cancel mirror worker in `stop()`

---

## Phase 3: Search Upgrade

### Task 3.1: FTS5 search in history.py

**File(s):** `scripts/history.py`

- [ ] Replace `scan_agent_history()` + `_scan_one()` with FTS5 query against local `mirrors_fts`
- [ ] Resolve daemon DB path: `TELECLAUDE_DB_PATH` env var → `config.database.path` → default `~/.teleclaude/teleclaude.db`. Open in read-only mode (`file:{path}?mode=ro`)
- [ ] Preserve existing output format (table with #, Date/Time, Agent, Project, Topic, Session columns)
- [ ] Preserve `--agent` filtering (now via SQL WHERE on `mirrors.agent`)
- [ ] Add `--computer <name> [<name2> ...]` flag (nargs='+')

### Task 3.2: Daemon mirror search API

**File(s):** `teleclaude/mirrors/api_routes.py` (new)

Endpoints for remote search (used by `--computer` flag):

- [ ] `GET /api/mirrors/search?q=<terms>&agent=<agent>&limit=<n>` → FTS5 query against local mirrors table, returns JSON array of mirror search results
- [ ] `GET /api/mirrors/<session_id>` → returns single mirror record (conversation text)
- [ ] `GET /api/mirrors/<session_id>/transcript` → streams the raw JSONL transcript file content for forensic drill-down

### Task 3.3: Register API routes

**File(s):** `teleclaude/api_server.py`

- [ ] Import mirror router from `teleclaude/mirrors/api_routes.py`
- [ ] Register via `self.app.include_router(mirror_router)` — follows the existing pattern used by memory_router, hooks_router, channels_router, streaming_router, data_router, todo_router

### Task 3.4: Remote search in history.py

**File(s):** `scripts/history.py`

- [ ] `--computer <name> [<name2> ...]`: resolve each computer name to daemon API URL using computer discovery (query local daemon API for heartbeat/cache data)
- [ ] Send parallel search queries to `GET /api/mirrors/search` on each remote daemon
- [ ] Assemble results tagged by computer name, sort by time
- [ ] Display in the same format as local search
- [ ] Fallback: if remote daemon unreachable, print error message per computer (not crash)

### Task 3.5: Show mirror and raw transcript

**File(s):** `scripts/history.py`

- [ ] `--show SESSION`: if no `--computer`, fetch mirror from local DB by session_id, render `conversation_text` as formatted output. If not found locally, it's not found.
- [ ] `--show SESSION --raw`: if session is local, render from local JSONL (existing `show_transcript()` path). If `--computer` specified, fetch from remote daemon's `GET /api/mirrors/<session_id>/transcript`
- [ ] If `--computer` specified with `--show`, fetch from that computer's daemon
- [ ] Add `--raw` flag to argparse

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Test mirror generation from a sample JSONL transcript (conversation extraction, system-reminder stripping, empty transcript handling)
- [ ] Test fan-out processor registry (register, dispatch, error isolation)
- [ ] Test FTS5 search against mirrors table (match, no-match, multi-word AND logic)
- [ ] Test `--computer` flag routing (mock daemon API, parallel queries)
- [ ] Test mirror search API endpoints
- [ ] Test migration up/down
- [ ] Test background worker reconciliation logic (stale detection, idempotent re-run)
- [ ] Run `make test`

### Task 4.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain
- [ ] Verify daemon starts cleanly with migration applied
- [ ] Verify `history.py` works with daemon down (read-only access to local mirrors)
- [ ] Verify AGENT_STOP triggers mirror regeneration within the same agent turn
- [ ] Verify SESSION_CLOSED triggers final mirror generation
- [ ] Verify background worker catches sessions that events missed

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
