# Requirements: history-search-upgrade

## Goal

Replace the brute-force transcript scanning in `history.py` with a searchable conversation mirror layer backed by FTS5 in the daemon SQLite database. Mirrors capture only the natural conversation (what was discussed, decided, concluded). Each computer stores only its own mirrors. Cross-computer search is done via live API calls to the remote daemon — no replication of mirror data between computers.

## Scope

### In scope

- **Database migration** (`025_add_mirrors_table.py`): `mirrors` content table + `mirrors_fts` FTS5 virtual table with auto-sync triggers. Follows the `memory_observations` / `memory_observations_fts` pattern from migration 005.
- **Mirror generator module** (`teleclaude/mirrors/generator.py`): extracts conversation-only text from JSONL transcripts using `extract_structured_messages(transcript_path, agent_name, include_tools=False, include_thinking=False)` where `agent_name` is an `AgentName` enum. Strips `<system-reminder>` tags from user messages via regex. Writes to `mirrors` table via `INSERT OR REPLACE`.
- **Event-driven generation (primary)**: AGENT_STOP hook event triggers mirror regeneration after every agent turn — near-real-time search currency. SESSION_CLOSED event bus event triggers final mirror generation on session close. Both events dispatch to a fan-out processor registry; mirrors is processor #1.
- **Fan-out architecture**: the event handler dispatches to registered processors. Adding a future processor (e.g., metrics, observability) requires zero changes to event wiring — just register another processor.
- **Background worker (safety net)**: idempotent reconciliation loop in the daemon that compares transcript file mtime against `mirrors.updated_at` to find stale/new sessions. Runs on daemon startup and periodically (5-minute interval). Catches anything events missed (daemon was down, edge cases, first-run catchup). The worker IS the backfill — no separate backfill script.
- **Search upgrade**: replace `scan_agent_history()` + `_scan_one()` in `history.py` with FTS5 queries against the local daemon DB (read-only).
- **Remote search API**: daemon HTTP endpoints that accept search queries and return results from the local mirrors table. Used by `--computer` flag to query remote daemons on-the-fly.
- **Cross-computer search**: `--computer <name> [<name2> ...]` in history.py resolves remote daemons and sends parallel search requests. No mirror data is replicated — each computer owns only its sessions.
- **Show modes**: `--show SESSION` renders mirror conversation text. `--show SESSION --raw` fetches full transcript from the source computer via daemon API.

### Out of scope

- Replicating or distributing mirror data between computers (each computer stores only its own).
- Changing the raw transcript format or storage location.
- Modifying the `extract_structured_messages()` function signature (use as-is).
- Changes to the TUI.
- Notification service integration for operational reporting (soft dependency — built with log-based fallback, notification integration added when notification-service is delivered).

## Success Criteria

- [ ] `history.py --agent claude <terms>` returns results from local FTS5 mirrors table instead of scanning JSONL files.
- [ ] `history.py --agent all --computer <name> <terms>` sends a live search request to the remote daemon and returns results.
- [ ] `history.py --agent all --computer <name1> <name2> <terms>` queries multiple remote daemons in parallel and assembles results.
- [ ] `history.py --agent claude --show <session>` renders the conversation mirror as readable text.
- [ ] `history.py --agent claude --show <session> --raw` fetches and renders the full transcript from the source computer.
- [ ] Mirrors are generated in near-real-time via AGENT_STOP hook events (after every agent turn).
- [ ] Mirrors get a final generation via SESSION_CLOSED event on session close.
- [ ] The background worker catches any sessions that events missed and generates their mirrors within 5 minutes.
- [ ] The background worker's first run on a fresh install processes all existing transcripts (IS the backfill).
- [ ] Each computer stores only mirrors for sessions that ran on that computer — no cross-computer replication.
- [ ] Existing CLI flags (`--agent`, `--show`, `--thinking`, `--tail`) continue to work.
- [ ] The daemon DB remains a single file per the single-database policy.
- [ ] `history.py` reads the daemon DB in read-only mode and works even when the daemon is down (local mirrors still searchable).
- [ ] Adding a new event-driven processor requires zero changes to event wiring (fan-out architecture).

## Constraints

- **No mirror replication**: each computer stores only its own session mirrors. Cross-computer search is live API, not local data.
- **Single SQLite database file** per single-database policy — mirrors are a table in `teleclaude.db`.
- **Daemon owns all writes** to the mirrors table. `history.py` reads in read-only mode.
- **Agents use the CLI tool**, never SQLite directly.
- **Reuse `extract_structured_messages()`** from `teleclaude/utils/transcript.py`. Signature: `(transcript_path: str, agent_name: AgentName, *, since: Optional[str] = None, include_tools: bool = False, include_thinking: bool = False) -> list[StructuredMessage]`.
- **Migration follows the pattern** in `005_add_memory_tables.py` — content table + FTS5 virtual table + triggers. Next slot: `025`.
- **AGENT_STOP routing**: flows through `agent_coordinator.handle_event` (hook event), not through the event bus. Mirror processor hooks into this path.
- **SESSION_CLOSED routing**: standard event bus event via `event_bus.subscribe()`. Fires from `db.close_session()`, DB hard delete, `session_cleanup.replay_session_closed()`, and `command_handlers` session-end.
- **Transcript discovery**: mirror worker uses `AGENT_PROTOCOL` from `teleclaude.constants` (session_dir + log_pattern per agent). Does NOT import from `scripts/history.py`.
- **API route registration**: follows existing pattern — `teleclaude/mirrors/api_routes.py` with FastAPI router, included via `app.include_router()` in `teleclaude/api_server.py`.
- **Computer discovery**: uses existing heartbeat/cache infrastructure for computer-to-daemon-URL resolution.
- **Notification dependency (soft)**: mirror worker reports progress/completion through notification service when available. Log-based fallback until notification-service is delivered.

## Risks

- FTS5 index size with ~3,660 sessions of conversation text. Mitigated: FTS5 handles this scale easily; memory observations already use the same pattern.
- Remote daemon unavailability means remote search fails gracefully (error message per computer, not crash).
- System-reminder tag stripping requires regex on user message text. Mitigated: tags are always complete `<system-reminder>...</system-reminder>` blocks injected by hooks.
- AGENT_STOP routing through agent_coordinator (not event bus) requires understanding the hook event handling path. Mitigated: pattern is well-documented in daemon.py and agent_coordinator.
