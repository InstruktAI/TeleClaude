# Implementation Plan: history-search-upgrade

## Overview

The upgrade replaces brute-force JSONL scanning with a three-layer architecture: **generation** (daemon extracts conversation from transcripts into SQLite), **distribution** (Redis Streams fanout to other computers), **search** (FTS5 queries in `history.py`). Each layer is independent — generation works without distribution, search works without the daemon running. The implementation follows existing patterns: FTS5 from migration 005, fanout from deployment handler, read-only DB access from current `history.py`.

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
- [ ] Add indexes: `idx_mirrors_computer` on `(computer)`, `idx_mirrors_agent` on `(agent)`, `idx_mirrors_project` on `(project)`, `idx_mirrors_timestamp` on `(timestamp_start DESC)`
- [ ] Create `mirrors_fts` FTS5 virtual table: `USING fts5(title, conversation_text, content='mirrors', content_rowid='id')`
- [ ] Create triggers: `mirrors_ai` (after insert), `mirrors_ad` (after delete), `mirrors_au` (after update) — same pattern as `memory_obs_ai/ad/au`
- [ ] Implement `async def down(db)` to drop FTS triggers, virtual table, and content table

### Task 1.2: ~~Register migration in runner~~ (Not needed)

The migration runner auto-discovers `*.py` files matching `^\d{3}_` in the migrations directory. No explicit registration step is required — placing `025_add_mirrors_table.py` in the directory is sufficient.

---

## Phase 2: Generation Layer

### Task 2.1: Mirror generator module

**File(s):** `teleclaude/mirrors/generator.py` (new)

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
  4. Publishes updated mirrors to Redis Streams channel (if Redis available)
- [ ] Register as a daemon background task (follow pattern of existing daemon workers)
- [ ] Graceful shutdown via cancellation token

### Task 2.3: Session close hook

**File(s):** `teleclaude/mirrors/generator.py`, `teleclaude/daemon.py`

- [ ] In the daemon's `_handle_session_closed` handler, trigger final mirror generation for the closing session
- [ ] This supplements the background worker — ensures mirror is current when session ends

### Task 2.4: Package init

**File(s):** `teleclaude/mirrors/__init__.py` (new)

- [ ] Export `generate_mirror`, `MirrorWorker` (or equivalent entry point)

---

## Phase 3: Distribution Layer

### Task 3.1: Mirror channel publisher

**File(s):** `teleclaude/mirrors/channel.py` (new)

- [ ] `publish_mirror(redis, mirror_data, daemon_id)` → publishes mirror to `mirrors:conversations` Redis Stream via XADD
- [ ] Payload: `{session_id, computer, agent, project, title, timestamp_start, timestamp_end, conversation_text, message_count, metadata, daemon_id}`
- [ ] Follow deployment fanout pattern from `teleclaude/deployment/handler.py` — include `daemon_id` for self-origin skip
- [ ] Channel key: `mirrors:conversations` (constant)

### Task 3.2: Mirror channel consumer

**File(s):** `teleclaude/mirrors/channel.py`

- [ ] `consume_mirrors(redis, db, daemon_id)` → polls `mirrors:conversations` stream via XREAD (not XREADGROUP — fanout pattern)
- [ ] Skip messages from own `daemon_id` (self-origin skip)
- [ ] Materialize remote mirrors into local `mirrors` table via `INSERT OR REPLACE`
- [ ] Track last-read stream ID for resume after restart

### Task 3.3: Integrate channel into daemon startup

**File(s):** `teleclaude/daemon.py`

- [ ] Start mirror consumer as background task alongside existing channel workers
- [ ] Inject Redis accessor using same pattern as `configure_deployment_handler(get_redis=...)`
- [ ] Start mirror background worker as daemon task

---

## Phase 4: Search Upgrade

### Task 4.1: FTS5 search in history.py

**File(s):** `scripts/history.py`

- [ ] Replace `scan_agent_history()` + `_scan_one()` with FTS5 query: `SELECT ... FROM mirrors JOIN mirrors_fts ON mirrors.id = mirrors_fts.rowid WHERE mirrors_fts MATCH ? AND agent = ? ORDER BY timestamp_start DESC`
- [ ] Resolve daemon DB path: read `TELECLAUDE_DB_PATH` env var, fall back to `~/.teleclaude/teleclaude.db`. Open in read-only mode (`file:{path}?mode=ro`)
- [ ] Preserve existing output format (table with #, Date/Time, Agent, Project, Topic, Session columns)
- [ ] Preserve `--agent` filtering (already exists, now filters via SQL WHERE)
- [ ] Add `--computer` flag: default searches local mirrors, `--computer <name>` routes to remote daemon API

### Task 4.2: Remote search via daemon API

**File(s):** `teleclaude/mirrors/api_routes.py` (new), `scripts/history.py`

- [ ] Daemon endpoint: `GET /api/mirrors/search?q=<terms>&agent=<agent>&limit=<n>` → returns JSON array of mirror results
- [ ] `history.py --computer <name>` resolves computer to daemon API URL (using existing computer discovery) and calls the search endpoint
- [ ] Fallback: if remote daemon unreachable, print error and suggest local search

### Task 4.3: Show mirror and raw transcript

**File(s):** `scripts/history.py`

- [ ] `--show SESSION`: fetch mirror from local DB by session_id, render `conversation_text` as formatted output (user/assistant turns with timestamps)
- [ ] `--show SESSION --raw`: if mirror's `computer` matches local computer name, render from local JSONL (existing `show_transcript()`). If remote, fetch full transcript from source computer's daemon API endpoint
- [ ] Daemon endpoint: `GET /api/mirrors/<session_id>/raw` → streams the raw JSONL transcript file content

### Task 4.4: Register API routes

**File(s):** `teleclaude/daemon.py` or API route registration module

- [ ] Mount mirror API routes alongside existing daemon API endpoints

---

## Phase 5: Backfill

### Task 5.1: Backfill job

**File(s):** `teleclaude/mirrors/backfill.py` (new)

- [ ] CLI-invocable script or daemon command that processes all existing transcripts into mirrors
- [ ] Discovers all transcripts across agents, generates mirrors in batch
- [ ] Progress logging (every 100 sessions)
- [ ] Idempotent via `INSERT OR REPLACE` — safe to re-run

---

## Phase 6: Validation

### Task 6.1: Tests

- [ ] Test mirror generation from a sample JSONL transcript (conversation extraction, system-reminder stripping, empty transcript handling)
- [ ] Test FTS5 search against mirrors table (match, no-match, multi-word AND logic)
- [ ] Test `--computer` flag routing (local vs remote)
- [ ] Test channel publish/consume round-trip (mirror published → consumed → materialized)
- [ ] Test migration up/down
- [ ] Run `make test`

### Task 6.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain
- [ ] Verify daemon starts cleanly with migration applied
- [ ] Verify `history.py` works with daemon down (read-only access to existing mirrors)

---

## Phase 7: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
