# Implementation Plan: history-search-upgrade

## Overview

The upgrade replaces brute-force JSONL scanning with two layers: **generation** (daemon extracts conversation from transcripts into local SQLite) and **search** (FTS5 queries in `history.py`, with live API calls for remote computers). Each computer stores only its own mirrors — no cross-computer replication. Remote search is on-the-fly via the daemon API. The implementation follows existing patterns: FTS5 from migration 005, daemon background workers, read-only DB access.

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
- [ ] Create triggers: `mirrors_ai` (after insert), `mirrors_ad` (after delete), `mirrors_au` (after update) — same pattern as `memory_obs_ai/ad/au`
- [ ] Implement `async def down(db)` to drop FTS triggers, virtual table, indexes, and content table

The migration runner auto-discovers `*.py` files matching `^\d{3}_` in the migrations directory — no explicit registration needed.

---

## Phase 2: Generation Layer

### Task 2.1: Mirror generator module

**File(s):** `teleclaude/mirrors/__init__.py` (new), `teleclaude/mirrors/generator.py` (new)

- [ ] `generate_mirror(session_id, transcript_path, agent, computer, project, db)` → extracts conversation text using `extract_structured_messages(path, agent, include_tools=False, include_thinking=False)`, strips `<system-reminder>...</system-reminder>` from user messages via regex, joins into conversation_text, writes to `mirrors` table via `INSERT OR REPLACE`
- [ ] `strip_system_reminders(text)` → regex `re.sub(r'<system-reminder>.*?</system-reminder>', '', text, flags=re.DOTALL).strip()`
- [ ] Derive `title` from first user message (truncated), `timestamp_start`/`timestamp_end` from first/last message timestamps, `message_count` from count of extracted messages
- [ ] Handle edge cases: empty transcripts (skip), transcripts with only tool calls (skip — zero conversation messages)

### Task 2.2: Background mirror worker

**File(s):** `teleclaude/mirrors/worker.py` (new)

- [ ] Periodic background task (5–10 min interval) that:
  1. Discovers transcript files via `_discover_transcripts()` pattern from all agents
  2. Compares file mtime against `mirrors.updated_at` to find sessions needing regeneration
  3. Calls `generate_mirror()` for each stale/new transcript
- [ ] Register as a daemon background task (follow pattern of existing daemon workers)
- [ ] Graceful shutdown via cancellation token

### Task 2.3: Session close hook

**File(s):** `teleclaude/mirrors/generator.py`, `teleclaude/daemon.py`

- [ ] In the daemon's `_handle_session_closed` handler, trigger final mirror generation for the closing session
- [ ] This supplements the background worker — ensures mirror is current when session ends

### Task 2.4: Wire into daemon startup/shutdown

**File(s):** `teleclaude/daemon.py`

- [ ] Start mirror worker as background task in `start()`
- [ ] Cancel mirror worker in `stop()`

---

## Phase 3: Search Upgrade

### Task 3.1: FTS5 search in history.py

**File(s):** `scripts/history.py`

- [ ] Replace `scan_agent_history()` + `_scan_one()` with FTS5 query against local `mirrors_fts`
- [ ] Resolve daemon DB path: read `TELECLAUDE_DB_PATH` env var, fall back to `~/.teleclaude/teleclaude.db`. Open in read-only mode (`file:{path}?mode=ro`)
- [ ] Preserve existing output format (table with #, Date/Time, Agent, Project, Topic, Session columns)
- [ ] Preserve `--agent` filtering (now via SQL WHERE on `mirrors.agent`)
- [ ] Add `--computer` flag: when specified, send live search request to remote daemon API instead of querying local DB

### Task 3.2: Daemon mirror search API

**File(s):** `teleclaude/mirrors/api_routes.py` (new)

Endpoints for remote search (used by `--computer` flag):

- [ ] `GET /api/mirrors/search?q=<terms>&agent=<agent>&limit=<n>` → returns JSON array of mirror search results from the local mirrors table
- [ ] `GET /api/mirrors/<session_id>` → returns single mirror record (conversation text)
- [ ] `GET /api/mirrors/<session_id>/transcript` → streams the raw JSONL transcript file content for forensic drill-down

### Task 3.3: Remote search in history.py

**File(s):** `scripts/history.py`

- [ ] `--computer <name>`: resolve computer to daemon API URL using existing computer discovery (heartbeat/cache)
- [ ] Send search query to `GET /api/mirrors/search` on the remote daemon
- [ ] Display results in the same format as local search
- [ ] Fallback: if remote daemon unreachable, print error

### Task 3.4: Show mirror and raw transcript

**File(s):** `scripts/history.py`

- [ ] `--show SESSION`: fetch mirror from local DB by session_id, render `conversation_text` as formatted output
- [ ] `--show SESSION --raw`: if session is local, render from local JSONL (existing `show_transcript()`). If remote (session not found locally), fetch from source computer's `GET /api/mirrors/<session_id>/transcript`
- [ ] Add `--raw` flag to argparse

### Task 3.5: Register API routes

**File(s):** `teleclaude/daemon.py` or API route registration module

- [ ] Mount mirror API routes alongside existing daemon API endpoints

---

## Phase 4: Backfill

### Task 4.1: Backfill job

**File(s):** `teleclaude/mirrors/backfill.py` (new)

- [ ] CLI-invocable script or daemon command that processes all existing transcripts into mirrors
- [ ] Discovers all transcripts across agents, generates mirrors in batch
- [ ] Progress logging (every 100 sessions)
- [ ] Idempotent via `INSERT OR REPLACE` — safe to re-run

---

## Phase 5: Validation

### Task 5.1: Tests

- [ ] Test mirror generation from a sample JSONL transcript (conversation extraction, system-reminder stripping, empty transcript handling)
- [ ] Test FTS5 search against mirrors table (match, no-match, multi-word AND logic)
- [ ] Test `--computer` flag routing (mock daemon API)
- [ ] Test mirror search API endpoints
- [ ] Test migration up/down
- [ ] Run `make test`

### Task 5.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain
- [ ] Verify daemon starts cleanly with migration applied
- [ ] Verify `history.py` works with daemon down (read-only access to local mirrors)

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
