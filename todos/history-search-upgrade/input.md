# Input: history-search-upgrade

<!-- Converged design from AI-to-AI peer conversation (3 breath cycles, sessions f099c0ab + 137c5e46). -->

## Problem

Agent session transcripts contain everything — tool calls, thinking, system metadata. We need a searchable recall layer that captures only the natural conversation: what was discussed, decided, and concluded. This system must work across multiple computers.

## Core Concept

A **mirror** is a purpose-built recall artifact, not a degraded transcript. The transcript records what the agent _did_. The mirror records what was _discussed_. Different documents for different jobs.

**Evidence**: Real transcript analysis (session 1c178904, 813KB, 430 JSONL entries) showed 73 conversation-only messages (17% of entries). The conversation-only view is coherent — decisions, conclusions, and rationale are preserved because agents naturally summarize tool findings in their text responses.

## Two-Tier Architecture

- **Mirrors travel** — lightweight recall index distributed across computers via Redis channels
- **Raw transcripts stay home** — forensic archive on the originating machine

For recall ("what did we discuss about X?") — the mirror answers perfectly.
For forensics ("what was the exact error?") — the raw transcript on the source machine has it.
The mirror tells you WHAT happened and WHERE to look deeper.

## Three Independent Concerns

### Generation (where mirrors are created)

- Mirrors are generated locally, on the machine that ran the session (the only computer with the JSONL)
- **Trigger**: daemon background worker scans for sessions with new activity, regenerates mirrors periodically (~5-10 min). Final generation on session close (daemon cleanup path). Note: `SESSION_CLOSED` event is currently only emitted from Telegram adapter — not universal. Background worker is the robust approach.
- **Long-running sessions**: naturally handled by periodic worker — no special case needed
- **Extraction**: `extract_structured_messages(path, agent, include_tools=False, include_thinking=False)` — already exists in `teleclaude/utils/transcript.py`
- **Filtering**: strip empty text blocks (noise entries before tool work) and `<system-reminder>` tags in user messages (metadata, not conversation)
- **Backfill**: one-time agent job processes all existing ~3,660 transcripts. Batch migration, runs once overnight. After that, incremental.

### Distribution (how mirrors reach other computers)

- Published via Redis Streams channels (deployment fanout pattern as template)
- Channel: `mirrors:transcripts` (or scoped per project)
- Remote daemons consume and materialize into their local mirrors table
- Heartbeat + cache for computer discovery (existing infrastructure)
- What travels on the channel is the same regardless of local storage — the protocol is independent of materialization strategy

### Search (history.py upgrade)

- Default: searches local mirrors table via FTS5
- `--computer VALUE`: routes search to remote daemon API
- `--agent VALUE`: filters by agent type (claude, codex, gemini)
- `--show SESSION`: renders mirror content as readable text
- `--show SESSION --raw`: fetches full transcript from source computer via daemon API
- Single entry point for both recall and forensics — routing is hidden from the user

## Storage

- **mirrors table** in daemon SQLite database (not a separate DB file)
- FTS5 for full-text search across thousands of sessions
- Key columns: `session_id`, `computer`, `agent`, `project`, `title`, `timestamp_start`, `timestamp_end`, `conversation_text` (FTS5-indexed), `metadata` (JSON)
- INSERT OR REPLACE by `session_id` enables incremental updates without complexity
- Respects single-database policy: mirrors are a daemon DB table, history.py reads in read-only mode

## Ownership

- **Daemon**: generates mirrors (from transcripts), publishes to channel, consumes remote mirrors, writes to mirrors table
- **history.py**: reads daemon DB in read-only mode. Works even when daemon is down (existing mirrors still searchable, no new generation)
- **Agents**: use the history CLI tool. Never touch SQLite directly.

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
- DB: `aiosqlite`, path configurable via `TELECLAUDE_DB_PATH`

### Generation Triggers

- `SESSION_CLOSED` event exists but is **only emitted from Telegram adapter** and replay path — not universal
- `AGENT_STOP` fires on **every agent turn** (all agents: Claude SubagentStop, Codex agent_stop) — more universal but frequent
- Recommended approach: background worker that periodically scans for sessions with new activity, regenerates mirrors. Simple, robust, no event-wiring needed. Can add event-based optimization later.
- For session close: the daemon's session cleanup path could trigger final mirror generation

### Extraction

- `extract_structured_messages(path, agent, include_tools=False, include_thinking=False)` already filters perfectly
- Empty text blocks already skipped: `if text.strip():` at line 2172
- System-reminder tags: live **inside user text block content**, not as separate metadata entries. Need regex strip of `<system-reminder>...</system-reminder>` from user message text.
- Returns `StructuredMessage(role, type, text, timestamp, entry_index, file_index)`

### Redis Channels (full module exists)

- `teleclaude/channels/publisher.py`: `await publish(redis, channel, payload)` — XADD with JSON payload
- `teleclaude/channels/consumer.py`: XREADGROUP with consumer groups, auto-ack
- `teleclaude/channels/worker.py`: background polling worker (5s interval), filter matching, dispatch
- `teleclaude/channels/api_routes.py`: HTTP API for publish/list
- Channel naming: `channel:{project}:{topic}` — for mirrors: `channel:mirrors:conversations`
- **Deployment fanout** (`teleclaude/deployment/handler.py`): reference pattern using XREAD without consumer groups, self-origin skip via daemon_id

### Current History.py

- Brute-force scan: ThreadPoolExecutor with 8 workers scanning up to 500 JSONL files
- AND-logic word matching with 80-char context window
- `--show` mode: flexible session ID matching (prefix, extracted ID, substring)
- CLI flags: `--agent`, `--show`, `--thinking`, `--tail`, positional search terms
- Upgrade path: replace `scan_agent_history()` + `_scan_one()` with FTS5 query against mirrors table

## Design Process

This design was produced through a structured AI-to-AI peer conversation using three breath cycles (inhale/hold/exhale). Round 1 failed due to premature convergence and a fundamental error (designing text-level stripping when the data layer already solves extraction). Round 2 succeeded by: (1) questioning the premise ("agent sessions are not conversations"), (2) grounding in real data, (3) identifying the "recall" frame as primary use case, (4) separating generation/distribution/search as independent concerns, (5) resolving file-vs-SQLite with FTS5 argument, (6) resolving the cost question with the two-tier model. Infrastructure research confirmed alignment with existing patterns (FTS5 in memory search, channels module, migration system).
