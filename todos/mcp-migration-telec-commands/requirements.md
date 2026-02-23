# Requirements: mcp-migration-telec-commands

## Goal

Add `telec` subcommands for the 22 agent tools that don't yet have CLI
equivalents, calling the existing daemon REST API over the Unix socket.
(`telec docs` already covers `get_context` and `help` — see note below.)
Extend the REST API with new endpoints where needed. Write rich `--help`
text with behavioral guidance and usage examples that cover every parameter
and input shape. Update the telec-cli spec doc with `@exec` directives for
baseline tool detail. Enrich `telec docs --help` with two-phase flow guidance.

Add daemon-side role enforcement: every API endpoint checks the caller's
system role and human role before executing. This replaces the MCP wrapper's
file-based tool filtering with tamper-resistant server-side enforcement.

### `telec docs` already replaces `get_context`

The existing `telec docs` command already implements the full two-phase flow
from the `teleclaude__get_context` MCP tool:

- **Phase 1 (index):** `telec docs [--areas ...] [--domains ...] [--baseline-only] [--third-party]`
- **Phase 2 (get):** `telec docs id1,id2,id3` (comma-separated or space-separated IDs)

It calls `build_context_output()` directly — no REST API needed.

## Scope

### In scope

- Extend existing `telec` resource groups: `sessions` (new subcommands),
  `todo` (new subcommands for workflow state machines)
- Add new top-level commands: `computers`, `projects`, `deploy`
- Add new resource group: `agents` (status, availability)
- Add new resource group: `channels` (publish, list)
- Each subcommand calls the daemon REST API via httpx over the Unix socket
- Add missing REST API endpoints for tools that don't have them yet:
  - `sessions`: run-agent-command, stop-notifications
  - `todo`: next-prepare, next-work, next-maintain, mark-phase, set-dependencies
  - Top-level: deploy
    (Channels, agents, computers, projects already have REST endpoints)
- Daemon-side role enforcement on every endpoint (system_role + human_role check)
- `caller_session_id` injection from `$TMPDIR/teleclaude_session_id`
- JSON output to stdout, human-readable errors to stderr
- Graceful degradation when daemon is unavailable
- Rich `--help` for each subcommand (see Help Text Requirements below)
- Update `docs/global/general/spec/tools/telec-cli.md` with `@exec` directives
  for baseline tools
- Run `telec sync` to verify `@exec` expansion works
- Remove `telec claude`, `telec gemini`, `telec codex` aliases (unused by agents)

### Out of scope

- MCP removal (Phase 3, separate todo)
- Agent session config changes (Phase 2, separate todo)
- New CLI binary (we extend `telec`)

## CLI Structure (mirrors REST resources)

| `telec` command              | REST endpoint                       | New? |
| ---------------------------- | ----------------------------------- | ---- |
| `telec sessions list`        | `GET /sessions`                     | no   |
| `telec sessions start`       | `POST /sessions`                    | no   |
| `telec sessions send`        | `POST /sessions/{id}/message`       | no   |
| `telec sessions tail`        | `GET /sessions/{id}/messages`       | no   |
| `telec sessions run`         | `POST /sessions/run`                | yes  |
| `telec sessions end`         | `DELETE /sessions/{id}`             | no   |
| `telec sessions unsubscribe` | `POST /sessions/{id}/unsubscribe`   | yes  |
| `telec sessions result`      | `POST /sessions/{id}/result`        | yes  |
| `telec sessions file`        | `POST /sessions/{id}/file`          | no   |
| `telec sessions widget`      | `POST /sessions/{id}/widget`        | yes  |
| `telec sessions escalate`    | `POST /sessions/{id}/escalate`      | yes  |
| `telec todo prepare`         | `POST /todos/prepare`               | yes  |
| `telec todo work`            | `POST /todos/work`                  | yes  |
| `telec todo maintain`        | `POST /todos/maintain`              | yes  |
| `telec todo mark-phase`      | `POST /todos/mark-phase`            | yes  |
| `telec todo set-deps`        | `POST /todos/set-deps`              | yes  |
| `telec computers`            | `GET /computers`                    | no   |
| `telec projects`             | `GET /projects`                     | no   |
| `telec deploy`               | `POST /deploy`                      | yes  |
| `telec agents status`        | `POST /agents/{agent}/status`       | no   |
| `telec agents availability`  | `GET /agents/availability`          | no   |
| `telec channels list`        | `GET /api/channels/`                | no   |
| `telec channels publish`     | `POST /api/channels/{name}/publish` | no   |

New endpoints: 8 (sessions: 2, todos: 5, deploy: 1).
Existing endpoints: 15 (just need CLI wiring).

## Role Enforcement

Every REST endpoint checks the caller's identity and roles before executing.
See parent todo (`mcp-to-tool-specs/requirements.md`) for the full
permission matrix, enforcement flow, and attack/defense analysis.

### Dual-factor identity verification

`telec` sends two headers on every API call:

1. `X-Caller-Session-Id` — from `$TMPDIR/teleclaude_session_id` (file, writable)
2. `X-Tmux-Session` — from `tmux display-message -p '#S'` (tmux server, unforgeable)

The daemon cross-checks both against its DB before processing:

- Looks up the claimed session_id → retrieves stored `tmux_session_name`
- Compares stored tmux_session_name with the `X-Tmux-Session` header
- Mismatch → 403 "session identity mismatch" (blocks session_id forgery)
- Match → proceeds to role clearance check

This prevents privilege escalation by session_id tampering. The agent can
overwrite the file, but cannot control the tmux server's response about
which session it's physically running in.

### Role clearance check

After identity verification:

- Each endpoint declares its required system_role and human_role clearance
- Daemon checks `system_allowed AND human_allowed` from the permission matrix
- Returns 403 with clear message if denied
- No session_id → 401

### Graceful fallback for non-tmux callers

When `X-Tmux-Session` header is absent (e.g., TUI, API calls, tests),
the tmux cross-check is skipped. These callers are trusted — they access
the daemon directly, not through an agent sandbox.

This replaces the MCP wrapper's `role_tools.py` filtering. The exclusion
sets move from `WORKER_EXCLUDED_TOOLS` / `MEMBER_EXCLUDED_TOOLS` into
per-endpoint clearance declarations checked by the daemon.

## Help Text Requirements

### Structure

Every `--help` output must include:

1. **Usage line** — invocation syntax with positional args and flags
2. **Description** — what the tool does (1-3 sentences)
3. **Behavioral guidance** — when/how to use it, workflow patterns, constraints
   (migrated from MCP tool `description` fields)
4. **Arguments/Options** — all parameters with types, defaults, enums, required markers
5. **Examples** — usage examples covering every parameter and input shape

### Hard requirement: example coverage

Every input parameter and distinct input shape must be touched by at least
one example. This is the primary teaching mechanism for agents.

**For simple tools** (string/boolean flags): a few examples showing common
and edge-case invocations. Every flag must appear in at least one example.

**For complex tools** (JSON input like `render_widget`): multiple examples
illustrating different section types, nested structures, and variant
combinations.

### Source material for behavioral guidance

The MCP tool definitions in `teleclaude/mcp/tool_definitions.py` contain
rich description text with timer patterns, reason gates, required workflows,
section type references, and role constraints. This guidance must transfer
to the `--help` output.

## Existing REST API Coverage

15 of 23 tools already have REST endpoints. Only 8 new endpoints needed.

## Success Criteria

- [ ] `telec docs --help` documents the two-phase flow (index vs get by IDs)
- [ ] `telec sessions list` returns JSON session list
- [ ] `telec sessions start --computer local --project /path --title "Test"` creates session
- [ ] `telec sessions send --session-id X --message "hello"` sends message
- [ ] `telec todo prepare --slug my-item` returns preparation state
- [ ] `telec computers` returns computer list
- [ ] `telec deploy` triggers deployment
- [ ] `telec sessions result --session-id X --content "done"` sends result
- [ ] `telec channels list` returns active channels
- [ ] `telec --help` shows resource-based groups (sessions, todo, agents, channels)
- [ ] Every subcommand `--help` has examples covering all parameters
- [ ] Baseline tool `@exec` directives expand correctly in `telec sync`
- [ ] Daemon down → clear error message, non-zero exit code
- [ ] `caller_session_id` injected on every API call
- [ ] Output is valid JSON parseable by agents
- [ ] `telec claude`, `telec gemini`, `telec codex`, `telec list` removed
- [ ] `telec sessions list` replaces `telec list`
- [ ] Existing commands (`sync`, `todo`, `init`, `docs`) unaffected
- [ ] Daemon-side role enforcement returns 403 for denied commands
- [ ] Tmux cross-check returns 403 on session_id/tmux mismatch
- [ ] No session_id → 401 error
- [ ] Non-tmux callers (TUI, tests) bypass tmux check gracefully
- [ ] Permission matrix matches parent todo specification

## Constraints

- Extends the existing `telec` CLI — no new binary
- New REST endpoints call the same backend functions MCP handlers use
- Existing REST endpoints and TUI must not regress
- CLI structure mirrors REST resource paths — no invented groupings

## Risks

- Subcommand naming collisions with existing telec commands: audit first
- Large response bodies (session data): must handle correctly
- Some MCP handlers have complex logic (sessions.create with listener
  registration) that needs careful extraction into the REST handler
