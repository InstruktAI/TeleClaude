# Requirements: history-search-upgrade

## Goal

Replace the brute-force transcript scanning in `history.py` with a searchable conversation mirror layer backed by FTS5 in the daemon SQLite database. Mirrors capture only the natural conversation (what was discussed, decided, concluded). Each computer stores only its own mirrors. Cross-computer search is done via live API calls to the remote daemon — no replication of mirror data between computers.

## Scope

### In scope

- **Database migration** (`025_add_mirrors_table.py`): `mirrors` content table + `mirrors_fts` FTS5 virtual table with auto-sync triggers. Follows the `memory_observations` / `memory_observations_fts` pattern from migration 005.
- **Mirror generation**: daemon-side module that extracts conversation-only text from JSONL transcripts using `extract_structured_messages(path, agent, include_tools=False, include_thinking=False)`. Strips `<system-reminder>` tags from user messages. Writes to `mirrors` table via `INSERT OR REPLACE`.
- **Generation trigger**: background worker in the daemon that periodically scans for sessions with new transcript activity and regenerates their mirrors. Final mirror generation on session close via the daemon's existing cleanup path.
- **Search upgrade**: replace `scan_agent_history()` + `_scan_one()` in `history.py` with FTS5 queries against the local daemon DB (read-only).
- **Remote search API**: daemon HTTP endpoint that accepts search queries and returns results from the local mirrors table. Used by `--computer` flag to query remote daemons on-the-fly.
- **Cross-computer search**: `--computer <name>` in history.py resolves the remote daemon and sends a live search request. No mirror data is replicated — each computer owns only its sessions.
- **Show modes**: `--show SESSION` renders mirror conversation text. `--show SESSION --raw` fetches full transcript from the source computer via daemon API.
- **Backfill**: one-time job that processes all existing transcripts into mirrors.

### Out of scope

- Replicating or distributing mirror data between computers (each computer stores only its own).
- Redis Streams channels for mirror distribution (not needed — search is live API).
- Changing the raw transcript format or storage location.
- Modifying the `extract_structured_messages()` function signature (use as-is).
- Real-time streaming of mirrors (periodic generation is sufficient).
- Changes to the TUI.

## Success Criteria

- [ ] `history.py --agent claude <terms>` returns results from local FTS5 mirrors table instead of scanning JSONL files.
- [ ] `history.py --agent all --computer <name> <terms>` sends a live search request to the remote daemon and returns results.
- [ ] `history.py --agent claude --show <session>` renders the conversation mirror as readable text.
- [ ] `history.py --agent claude --show <session> --raw` fetches and renders the full transcript from the source computer.
- [ ] Mirrors are generated automatically for new sessions within ~10 minutes of activity.
- [ ] Each computer stores only mirrors for sessions that ran on that computer — no cross-computer replication.
- [ ] Existing CLI flags (`--agent`, `--show`, `--thinking`, `--tail`) continue to work.
- [ ] The daemon DB remains a single file per the single-database policy.
- [ ] `history.py` reads the daemon DB in read-only mode and works even when the daemon is down (local mirrors still searchable).

## Constraints

- **No mirror replication**: each computer stores only its own session mirrors. Cross-computer search is live API, not local data.
- Single SQLite database file per single-database policy — mirrors are a table in `teleclaude.db`.
- Daemon owns all writes to the mirrors table. `history.py` reads in read-only mode.
- Agents use the CLI tool, never SQLite directly.
- Mirror generation reuses `extract_structured_messages()` from `teleclaude/utils/transcript.py`.
- Migration follows the pattern in `005_add_memory_tables.py` — content table + FTS5 virtual table + triggers.
- Next migration slot: `025_add_mirrors_table.py`.
- Computer discovery uses existing heartbeat/cache infrastructure.

## Risks

- FTS5 index size with ~3,660 sessions of conversation text. Mitigated: FTS5 handles this scale easily; memory observations already use the same pattern.
- `SESSION_CLOSED` event is only emitted from Telegram adapter — not universal. Mitigated: primary trigger is a background worker scanning for activity, not events.
- Remote daemon unavailability means remote search fails gracefully (error message, not crash).
- System-reminder tag stripping requires regex on user message text. Mitigated: tags are always complete `<system-reminder>...</system-reminder>` blocks injected by hooks.
