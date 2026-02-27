# Input: history-search-upgrade

<!-- Converged design from AI-to-AI peer conversation (3 breath cycles, sessions f099c0ab + 137c5e46). Updated in brainstorm session 3d2880de with refined generation architecture and dependency decisions. -->

## Problem

Agent session transcripts contain everything — tool calls, thinking, system metadata. We need a searchable recall layer that captures only the natural conversation: what was discussed, decided, and concluded. This system must work across multiple computers.

## Core Concept

A **mirror** is a purpose-built recall artifact, not a degraded transcript. The transcript records what the agent _did_. The mirror records what was _discussed_. Different documents for different jobs.

**Evidence**: Real transcript analysis (session 1c178904, 813KB, 430 JSONL entries) showed 73 conversation-only messages (17% of entries). The conversation-only view is coherent — decisions, conclusions, and rationale are preserved because agents naturally summarize tool findings in their text responses.

## Architecture

- **Mirrors stay home** — each computer generates and stores only its own session mirrors in its daemon DB
- **Raw transcripts stay home** — forensic archive on the originating machine
- **Cross-computer search is live** — `--computer <name>` sends search requests to remote daemon APIs on-the-fly; no mirror data is replicated between computers

For recall ("what did we discuss about X?") — query the local mirrors, or query a remote daemon via API.
For forensics ("what was the exact error?") — the raw transcript on the source machine has it.
The mirror tells you WHAT happened and WHERE to look deeper.

## Three Independent Concerns

### Generation (where mirrors are created)

- Mirrors are generated locally, on the machine that ran the session (the only computer with the JSONL)
- **Primary trigger: AGENT_STOP event** — fires after every agent turn. Mirror is regenerated immediately for that session. Gives near-real-time search currency.
- **Secondary trigger: SESSION_CLOSED event** — fires from multiple sources (Telegram adapter, Discord adapter, session cleanup replay, cache manager). Final mirror generation on session close. Belt-and-suspenders.
- **Safety net: background worker** — idempotent reconciliation loop that catches anything events missed (daemon was down, edge cases, first-run catchup). Compares file mtime against `mirrors.updated_at` to find stale/new sessions. Runs on daemon startup and periodically after that. The worker IS the backfill — first pass processes everything, subsequent passes catch stragglers.
- **No separate backfill script.** The worker's reconciliation is idempotent by design. Run it anytime — after install, after weeks of inactivity, after daemon restart. Same code path. It always produces the correct state.
- **Long-running sessions**: naturally handled by AGENT_STOP event — mirror updates after every turn.
- **Extraction**: `extract_structured_messages(transcript_path: str, agent_name: AgentName, *, since=None, include_tools=False, include_thinking=False) -> list[StructuredMessage]` from `teleclaude/utils/transcript.py`. Note: `agent_name` is an `AgentName` enum, returns `StructuredMessage` dataclass with `.role`, `.type`, `.text`, `.timestamp` fields.
- **Filtering**: strip empty text blocks (already handled by `if text.strip():` in extraction) and `<system-reminder>...</system-reminder>` tags in user messages via regex.

### Event-driven extraction with fan-out

The event handler for AGENT_STOP/SESSION_CLOSED uses a **fan-out architecture**: the handler dispatches to registered processors. Mirrors is processor #1. The fan-out design means adding a future processor (e.g., metrics, observability) requires zero changes to the event wiring — just register another processor.

Only the mirrors processor is implemented now. The fan-out is the architectural pattern, not premature infrastructure.

### Cross-Computer Search (live API, no replication)

- **Hard requirement**: no mirror data is replicated between computers. Each computer stores only its own sessions.
- **No `--computer` flag**: search defaults to local mirrors table (FTS5 query, no API call). Results are flat — no computer grouping.
- **`--computer <name> [<name2> ...]`**: one or more computers specified. Parallel search requests sent to each remote daemon's `/api/mirrors/search`. Results assembled, tagged by computer name, sorted by time.
- **`--show SESSION`**: if no `--computer`, look in local mirrors. If not found locally, it's not found. If `--computer` specified, fetch from that computer's daemon.
- **`--show SESSION --raw`**: same routing. Local → local JSONL. Remote → remote daemon's `/api/mirrors/<session_id>/transcript` endpoint.
- Computer-to-daemon-URL resolution: query local daemon API (computer discovery via heartbeat/cache).
- If remote daemon unreachable, error message per computer, not crash.

### Search (history.py rewrite)

The old `scripts/history.py` gets **rewritten** — the brute-force JSONL scanner is replaced with FTS5 queries against the mirrors table. The file name could improve to reflect its actual purpose (search/recall tool), but that's a naming decision for implementation.

- Default: searches local mirrors table via FTS5
- `--computer VALUE [VALUE ...]`: routes search to remote daemon API(s) in parallel
- `--agent VALUE`: filters by agent type (claude, codex, gemini)
- `--show SESSION`: renders mirror conversation text
- `--show SESSION --raw`: renders full transcript from source
- Single entry point for both recall and forensics — routing is hidden from the user

## Storage

- **mirrors table** in daemon SQLite database (not a separate DB file)
- FTS5 for full-text search across thousands of sessions
- Key columns: `session_id`, `computer`, `agent`, `project`, `title`, `timestamp_start`, `timestamp_end`, `conversation_text` (FTS5-indexed), `message_count`, `metadata` (JSON)
- INSERT OR REPLACE by `session_id` enables incremental updates without complexity
- Respects single-database policy: mirrors are a daemon DB table, history.py reads in read-only mode

## Ownership

- **Daemon**: generates mirrors (event-driven + worker safety net), writes to local mirrors table, serves mirror search API for remote queries
- **history.py** (or renamed search tool): reads daemon DB in read-only mode. Works even when daemon is down (existing mirrors still searchable, no new generation)
- **Agents**: use the CLI tool. Never touch SQLite directly.

## Operational Reporting

The mirror worker reports its progress and completion through the **notification service** (see `todos/notification-service/`). This is a dependency — the notification service must exist before the mirror worker can report through it.

Progress notifications: "Mirror indexing: 0/3660" → "1200/3660" → "3660/3660 complete in 4m 12s". These use the notification service's progress update semantics (silent in-place updates until terminal completion).

## What the Mirror Captures

- User text messages (`role=user`, `type=text`)
- Agent text responses (`role=assistant`, `type=text`)

## What the Mirror Filters

- `tool_use` blocks — mechanism, not conversation
- `tool_result` blocks — mechanism, not conversation
- `thinking` blocks — internal reasoning, not output
- Empty text blocks — noise before tool work
- `<system-reminder>` tags in user messages — metadata injected by hooks/CLAUDE.md loading

## What Is Lost (acceptable cost)

- Specific file paths the agent read but didn't mention in text output
- Raw error messages that only appeared in tool results
- Exact command outputs (pytest runs, grep results, etc.)
- The precise sequence of tool operations

These are available via `--show SESSION --raw` drill-down to the source computer.

## Infrastructure Alignment (verified against codebase)

### Database

- 15 existing tables in `teleclaude/core/schema.sql`
- **FTS5 already in use**: `memory_observations_fts` table in migration `005_add_memory_tables.py` — exact pattern to follow (content table + FTS5 virtual table + auto-sync triggers)
- Migration system: `teleclaude/core/migrations/NNN_name.py` with `async def up(db)` / `async def down(db)`. Next: `025_add_mirrors_table.py`
- DB path resolution: `TELECLAUDE_DB_PATH` env var → `config.database.path` → default `~/.teleclaude/teleclaude.db`

### Generation Triggers

- **AGENT_STOP**: fires on every agent turn (all agents). Primary trigger for near-real-time mirror currency.
- **SESSION_CLOSED**: fires from Telegram adapter, Discord adapter, session cleanup replay, cache manager. Secondary trigger for final mirror state.
- **Background worker**: idempotent reconciliation on startup + periodic interval (5 minutes). Safety net.

### Extraction

- `extract_structured_messages(transcript_path: str, agent_name: AgentName, *, since: Optional[str] = None, include_tools: bool = False, include_thinking: bool = False) -> list[StructuredMessage]`
- `AgentName` is an enum from `teleclaude.core.agents`
- Returns `StructuredMessage(role: str, type: str, text: str, timestamp: Optional[str], entry_index: int, file_index: int)`
- Empty text blocks already skipped: `if text.strip():` at line 2172
- System-reminder tags: live inside user text block content. Need regex strip: `re.sub(r'<system-reminder>.*?</system-reminder>', '', text, flags=re.DOTALL).strip()`

### Transcript Discovery

The mirror worker (daemon module in `teleclaude/mirrors/worker.py`) implements its own transcript discovery using `AGENT_PROTOCOL` from `teleclaude.constants`. It does NOT import from `scripts/history.py` — that's across the module boundary and violates the scripts portability policy.

### Daemon API

- Routes live in `teleclaude/api_server.py` using FastAPI
- Existing pattern: separate route modules (`teleclaude/hooks/api_routes.py`, `teleclaude/channels/api_routes.py`)
- Mirror routes: create `teleclaude/mirrors/api_routes.py`, mount in `api_server.py`
- Endpoints: `GET /api/mirrors/search?q=<terms>&agent=<agent>&limit=<n>`, `GET /api/mirrors/<session_id>`, `GET /api/mirrors/<session_id>/transcript`

### Daemon Background Tasks

- Pattern: `asyncio.create_task()` in `start()`, cancel in `stop()`, track via `_track_background_task()`, done callback via `_log_background_task_exception()`
- Mirror worker follows this exact pattern.
- Wire into daemon startup/shutdown in `teleclaude/daemon.py`

### Current History.py

- Brute-force scan: ThreadPoolExecutor with 8 workers scanning up to 500 JSONL files
- AND-logic word matching with 80-char context window
- `--show` mode: flexible session ID matching (prefix, extracted ID, substring)
- CLI flags: `--agent`, `--show`, `--thinking`, `--tail`, positional search terms
- Imports from `teleclaude` (repo-only exception per scripts policy)
- Upgrade: replace `scan_agent_history()` + `_scan_one()` with FTS5 query against mirrors table

## Dependencies

- **notification-service**: mirror worker reports progress/completion through the notification service. Must exist before mirror worker can report properly. However, this is a soft dependency — the mirror worker can be built first with a simple log-based fallback, and notification integration added when the notification service is ready.

## Design Process

Original design produced through AI-to-AI peer conversation (3 breath cycles, sessions f099c0ab + 137c5e46). Refined in brainstorm session 3d2880de where the following decisions were made:

1. **Event-driven primary, worker as safety net** — reversed the original priority (worker primary, events supplementary)
2. **No separate backfill script** — the worker's idempotent reconciliation IS the backfill
3. **SESSION_CLOSED fires from multiple sources** — corrected factual error that it was Telegram-only
4. **Fan-out architecture** — event handler dispatches to processors, mirrors is #1, extensible without rework
5. **Precise function signatures** — corrected to match actual codebase (`AgentName` enum, `StructuredMessage` return type)
6. **API route registration** — pinned to `teleclaude/mirrors/api_routes.py` mounted in `api_server.py`
7. **Computer routing** — no flag = local only, one or more computers = parallel remote queries
8. **Notification service dependency** — operational reporting goes through notification service
