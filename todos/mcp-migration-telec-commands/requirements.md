# Requirements: mcp-migration-telec-commands

## Goal

Add `telec` subcommands for all 24 agent tools, calling the existing daemon
REST API over the Unix socket. Extend the REST API with new endpoints where
needed. This creates the invocation backbone that replaces MCP tool calls.

## Scope

### In scope

- Add `telec` subcommand groups: `sessions`, `workflow`, `infra`, `delivery`,
  `channels` (matching the tool taxonomy)
- Each subcommand calls the daemon REST API via httpx over the Unix socket
- Add missing REST API endpoints for the 16 tools that don't have them yet:
  - `context`: get-context, help
  - `sessions`: run-agent-command, stop-notifications
  - `workflow`: next-prepare, next-work, next-maintain, mark-phase, set-dependencies
  - `infra`: deploy, mark-agent-status
  - `delivery`: send-result, render-widget, escalate
  - `channels`: publish, channels-list
- `caller_session_id` injection from `$TMPDIR/teleclaude_session_id`
- JSON output to stdout, human-readable errors to stderr
- Graceful degradation when daemon is unavailable
- `--help` for each group and subcommand
- Remove `telec claude`, `telec gemini`, `telec codex` aliases (unused by agents)

### Out of scope

- Tool spec documentation (Phase 2, separate todo)
- Context-selection / AGENTS.md updates (Phase 3)
- MCP removal (later phase)
- New CLI binary (we extend `telec`)

## Existing REST API Coverage

8 of 24 tools already have REST endpoints:

| Tool             | Existing endpoint             |
| ---------------- | ----------------------------- |
| list-sessions    | `GET /sessions`               |
| start-session    | `POST /sessions`              |
| send-message     | `POST /sessions/{id}/message` |
| get-session-data | `GET /sessions/{id}/messages` |
| end-session      | `DELETE /sessions/{id}`       |
| list-computers   | `GET /computers`              |
| list-projects    | `GET /projects`               |
| send-file        | `POST /sessions/{id}/file`    |

The remaining 16 need new REST endpoints on the daemon API server.

## Success Criteria

- [ ] `telec sessions list` returns JSON session list
- [ ] `telec sessions create --computer local --project /path --title "Test"` creates session
- [ ] `telec sessions message --session-id X --message "hello"` sends message
- [ ] `telec workflow prepare --slug my-item` returns preparation state
- [ ] `telec infra computers` returns computer list
- [ ] `telec infra deploy` triggers deployment
- [ ] `telec delivery result --session-id X --content "done"` sends result
- [ ] `telec channels list` returns active channels
- [ ] `telec --help` shows new subcommand groups alongside existing ones
- [ ] Daemon down → clear error message, non-zero exit code
- [ ] `caller_session_id` injected on every API call
- [ ] Output is valid JSON parseable by agents
- [ ] `telec claude`, `telec gemini`, `telec codex` removed
- [ ] Existing commands (`sync`, `todo`, `init`, `docs`, `list`) unaffected

## Constraints

- Extends the existing `telec` CLI — no new binary
- New REST endpoints call the same backend functions MCP handlers use
- Existing REST endpoints and TUI must not regress

## Risks

- Subcommand naming collisions with existing telec commands: audit first
- Large response bodies (session data): must handle correctly
- Some MCP handlers have complex logic (sessions.create with listener
  registration) that needs careful extraction into the REST handler
