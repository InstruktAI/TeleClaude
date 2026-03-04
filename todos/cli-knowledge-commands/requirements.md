# Requirements: cli-knowledge-commands

## Goal

Bring history search and memory management into the `telec` CLI namespace as
first-class subcommands (`telec history`, `telec memories`), then retire the
standalone tool specs that teach agents to use raw scripts and curl calls.

## Problem Statement

Agents currently learn three separate tools for knowledge operations:

1. `history.py` — standalone script at `~/.teleclaude/scripts/history.py`
2. Memory API — raw `curl` to unix socket (`/api/memory/*`)
3. Agent restart — raw `curl` to unix socket (already covered by `telec sessions restart self`)

These are taught via three dedicated tool spec snippets in the expanded baseline,
consuming startup context on every session. The `telec` CLI already has a `CommandDef`
schema, help generation, and the daemon API client. The commands should live there.

## Scope

### In scope

1. **`telec history` subcommand** — thin CLI wrapper over history search functionality:
   - `telec history search [--agent <name|all>] <terms...>` — search transcripts
   - `telec history show <session-id> [--agent <name>] [--thinking] [--tail N]` — show transcript
   - Imports from `teleclaude.history.search` (extract reusable functions from
     `scripts/history.py` into a proper package module so both can share the logic)
   - After `history-search-upgrade` lands, this delegates to FTS5 queries instead

2. **`telec memories` subcommand** — thin CLI wrapper over the daemon memory API:
   - `telec memories search <query> [--limit N] [--type <type>] [--project <name>]` — search memories
   - `telec memories save <text> [--title <title>] [--type <type>] [--project <name>]` — save observation
   - `telec memories delete <id>` — delete observation
   - `telec memories timeline <id> [--before N] [--after N]` — show context around an observation
   - Uses `TelecAPIClient` to call daemon routes (not raw curl)

3. **`CommandDef` registration** — add both to `CLI_SURFACE` with flags, descriptions, notes.

4. **Tool spec retirement**:
   - Remove `general/spec/tools/agent-restart` (already redundant)
   - Remove `general/spec/tools/history-search` (replaced by `telec history`)
   - Remove `general/spec/tools/memory-management-api` (replaced by `telec memories`)
   - Update `docs/global/baseline.md` to remove the three retired refs
   - The `telec-cli` spec auto-generates from `CLI_SURFACE`, so new commands appear automatically

5. **Telec CLI spec update** — add canonical examples for both subcommands to the
   `telec-cli` spec's "Canonical fields" section (same pattern as `telec docs`, `telec sessions`).

### Out of scope

- Changing the memory API routes or storage layer.
- Changing `history.py` internals (the `history-search-upgrade` todo owns that).
- Adding new memory features beyond what the API already supports.
- TUI integration for memories or history.

## Success Criteria

- [ ] `telec history search --agent claude "config wizard"` returns matching sessions.
- [ ] `telec history show <session-id>` renders transcript text.
- [ ] `telec memories search "session reason"` returns matching observations.
- [ ] `telec memories save "Important finding" --title "Discovery" --type discovery --project teleclaude` saves an observation and prints the ID.
- [ ] `telec memories delete 123` deletes the observation.
- [ ] `telec memories timeline 42 --before 3 --after 3` shows surrounding observations.
- [ ] `telec -h` shows `history` and `memories` in the command list.
- [ ] `telec history -h` and `telec memories -h` show correct subcommand help.
- [ ] `general/spec/tools/agent-restart` snippet file is deleted.
- [ ] `general/spec/tools/history-search` snippet file is deleted.
- [ ] `general/spec/tools/memory-management-api` snippet file is deleted.
- [ ] `docs/global/baseline.md` no longer references the three deleted specs.
- [ ] The `telec-cli` spec (via `@exec` directives) shows both new subcommands.
- [ ] Agents using `telec memories save` and `telec history search` in sessions work correctly.

## Constraints

- `telec history` must work when the daemon is down (reads transcript files directly,
  same as `history.py`). After `history-search-upgrade`, local FTS5 reads still work
  without the daemon.
- `telec memories` requires the daemon (API calls). If daemon is down, print a clear
  error message — same pattern as other daemon-dependent commands.
- Both commands follow the `_handle_*` dispatch pattern in `telec.py`.
- Memory types must match `ObservationType` enum: preference, decision, discovery,
  gotcha, pattern, friction, context.
- No new Python dependencies.

## Dependencies

- None blocking. `history-search-upgrade` is independent — when it lands, `telec history`
  automatically benefits because it delegates to the same underlying module.

## Risks

- Negligible. All functionality already exists behind scripts/API. This is a surface
  consolidation, not new behavior.
