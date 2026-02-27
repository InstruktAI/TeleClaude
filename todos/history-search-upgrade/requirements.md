# Requirements: history-search-upgrade

## Goal

Replace the brute-force transcript scanning in `history.py` with a searchable conversation mirror layer backed by FTS5 in the daemon SQLite database. Mirrors capture only the natural conversation (what was discussed, decided, concluded) and are distributed across computers via Redis Streams so that any machine can search any other machine's session history.

## Scope

### In scope

- **Database migration** (`025_add_mirrors_table.py`): `mirrors` content table + `mirrors_fts` FTS5 virtual table with auto-sync triggers. Follows the `memory_observations` / `memory_observations_fts` pattern from migration 005.
- **Mirror generation**: daemon-side module that extracts conversation-only text from JSONL transcripts using `extract_structured_messages(path, agent, include_tools=False, include_thinking=False)`. Strips `<system-reminder>` tags from user messages. Writes to `mirrors` table via `INSERT OR REPLACE`.
- **Generation trigger**: background worker in the daemon that periodically scans for sessions with new transcript activity and regenerates their mirrors. Final mirror generation on session close via the daemon's existing cleanup path.
- **Distribution**: publish mirror data to a Redis Streams channel (`mirrors:conversations`) using the deployment fanout pattern (XREAD, self-origin skip via daemon_id). Remote daemons consume and materialize into their local `mirrors` table.
- **Search upgrade**: replace `scan_agent_history()` + `_scan_one()` in `history.py` with FTS5 queries against the daemon DB (read-only). Add `--computer` flag for remote search via daemon API.
- **Remote search API**: daemon HTTP endpoint that accepts search queries and returns results from the local mirrors table.
- **Show modes**: `--show SESSION` renders mirror conversation text. `--show SESSION --raw` fetches full transcript from the source computer via daemon API.
- **Backfill**: one-time job that processes all existing transcripts into mirrors.

### Out of scope

- Changing the raw transcript format or storage location.
- Modifying the `extract_structured_messages()` function signature (use as-is).
- Real-time streaming of mirrors (periodic generation is sufficient).
- Automatic transcript pruning or archival.
- Changes to the TUI.

## Success Criteria

- [ ] `history.py --agent claude <terms>` returns results from local FTS5 mirrors table instead of scanning JSONL files.
- [ ] `history.py --agent all --computer <name> <terms>` returns results from a remote computer's mirrors table.
- [ ] `history.py --agent claude --show <session>` renders the conversation mirror as readable text.
- [ ] `history.py --agent claude --show <session> --raw` fetches and renders the full transcript from the source computer.
- [ ] Mirrors are generated automatically for new sessions within ~10 minutes of activity.
- [ ] Mirrors are distributed to remote computers via Redis Streams and searchable there.
- [ ] Existing CLI flags (`--agent`, `--show`, `--thinking`, `--tail`) continue to work.
- [ ] The daemon DB remains a single file per the single-database policy.
- [ ] `history.py` reads the daemon DB in read-only mode and works even when the daemon is down (existing mirrors are still searchable).

## Constraints

- Single SQLite database file per single-database policy — mirrors are a table in `teleclaude.db`, not a separate file.
- Daemon owns all writes to the mirrors table. `history.py` reads in read-only mode.
- Agents use the CLI tool, never SQLite directly.
- Mirror generation reuses `extract_structured_messages()` from `teleclaude/utils/transcript.py` — no parallel extraction implementation.
- Redis Streams distribution follows the deployment fanout pattern from `teleclaude/deployment/handler.py` — XREAD (not XREADGROUP), self-origin skip via `daemon_id`.
- Migration follows the pattern in `005_add_memory_tables.py` — content table + FTS5 virtual table + triggers.
- Next migration slot: `025_add_mirrors_table.py`.

## Risks

- FTS5 index size with ~3,660 sessions of conversation text. Mitigated: FTS5 handles this scale easily; memory observations already use the same pattern.
- `SESSION_CLOSED` event is only emitted from Telegram adapter — not universal. Mitigated: primary trigger is a background worker scanning for activity, not events.
- Redis unavailability prevents distribution but not local operation. Mirrors are generated and searchable locally regardless of Redis state.
- System-reminder tag stripping requires regex on user message text. Risk of over-stripping if tags span content. Mitigated: tags are always complete `<system-reminder>...</system-reminder>` blocks injected by hooks.
