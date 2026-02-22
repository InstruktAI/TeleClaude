# Requirements: mcp-migration-telec-commands

## Goal

Add `telec` subcommands for the 22 agent tools that don't yet have CLI
equivalents, calling the existing daemon REST API over the Unix socket.
(`telec docs` already covers `get_context` and `help` — see note below.)
Extend the REST API with new endpoints where needed. Write rich `--help`
text with behavioral guidance and usage examples that cover every parameter
and input shape. Update the telec-cli spec doc with `@exec` directives for
baseline tool detail. Enrich `telec docs --help` with two-phase flow guidance.

This creates the invocation backbone AND the documentation layer that
replaces MCP tool calls.

### `telec docs` already replaces `get_context`

The existing `telec docs` command already implements the full two-phase flow
from the `teleclaude__get_context` MCP tool:

- **Phase 1 (index):** `telec docs [--areas ...] [--domains ...] [--baseline-only] [--third-party]`
- **Phase 2 (get):** `telec docs id1,id2,id3` (comma-separated or space-separated IDs)

It calls `build_context_output()` directly — no REST API needed. The naming
"docs" is intentional: this is documentation snippets, not generic "context".

The `teleclaude__help` MCP tool (TeleClaude capabilities summary) is a
standalone concern and belongs under `telec infra help` or `telec --help`
output, not a separate "context" group.

## Scope

### In scope

- Add `telec` subcommand groups: `sessions`, `workflow`, `infra`, `delivery`,
  `channels` (matching the tool taxonomy — no `context` group needed)
- Each subcommand calls the daemon REST API via httpx over the Unix socket
- Add missing REST API endpoints for the 12 tools that don't have them yet:
  - `sessions`: run-agent-command, stop-notifications
  - `workflow`: next-prepare, next-work, next-maintain, mark-phase, set-dependencies
  - `infra`: deploy, mark-agent-status
  - `delivery`: send-result, render-widget, escalate
    (Channels already have REST endpoints at `/api/channels/`)
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
combinations. The examples must cover enough of the discriminated union
surface that an agent can construct valid input without guessing.

**Coverage heuristic:** if you added a parameter, there must be an example
using it. If you have a JSON input with multiple shape variants, each
variant needs at least one example.

### Example: what rich `--help` looks like

```
Usage: telec start <computer> --project <path> --title <text> [options]

  Start a new AI agent session on a computer.

  REQUIRED WORKFLOW:
  1) Run `telec projects <computer>` first to discover available projects
  2) Use the exact path from that output in --project
  3) Returns session_id

  After dispatching: start a 5-minute background timer
  (sleep 300 in background). Wait for notification. If timer fires
  with no notification, check with `telec tail <session_id>`.

Arguments:
  computer                       Target computer name (required)

Options:
  --project <path>               Absolute project path from `telec projects` (required)
  --title <text>                 Session title (required)
  --agent <claude|gemini|codex>  Agent type (default: claude)
  --mode <fast|med|slow>         Model tier (default: slow)
  --message <text>               Initial prompt; omit for interactive session
  --direct                       Skip notification subscription (peer-to-peer)

Examples:
  # Start a Claude session on the workstation
  telec start workstation --project /home/user/myapp --title "Debug auth flow"

  # Start a fast Gemini session with an initial task
  telec start raspi --project /home/pi/app --title "Review PR" \
    --agent gemini --mode fast --message "Read README and summarize"

  # Peer-to-peer session (no notification subscription)
  telec start workstation --project /home/user/app --title "Collab" --direct
```

### Source material for behavioral guidance

The MCP tool definitions in `teleclaude/mcp/tool_definitions.py` contain
rich description text with:

- Timer patterns (`REMOTE_AI_TIMER_INSTRUCTION`)
- Reason gates and cadence gates (`get_session_data`)
- Required workflows (`start_session` list_projects prerequisite)
- Section type references (`render_widget`)
- Role constraints (`escalate` customer-only)

This guidance must transfer to the `--help` output, not be lost.

## Telec-CLI Spec Doc Update

The existing spec doc at `docs/global/general/spec/tools/telec-cli.md` already
uses `<!-- @exec: telec -h -->` and `<!-- @exec: telec docs -h -->`. Extend it
with `@exec` directives for all baseline tools:

```markdown
## CLI surface

<!-- @exec: telec -h -->

## Baseline tools

### `telec docs`

<!-- @exec: telec docs -h -->

### `telec list`

<!-- @exec: telec list -h -->

### `telec start`

<!-- @exec: telec start -h -->

### `telec send`

<!-- @exec: telec send -h -->

### `telec sessions run`

<!-- @exec: telec sessions run -h -->

### `telec tail`

<!-- @exec: telec tail -h -->

### `telec deploy`

<!-- @exec: telec deploy -h -->
```

## Existing REST API Coverage

10 of 24 tools already have REST endpoints:

| Tool             | Existing endpoint                   |
| ---------------- | ----------------------------------- |
| list-sessions    | `GET /sessions`                     |
| start-session    | `POST /sessions`                    |
| send-message     | `POST /sessions/{id}/message`       |
| get-session-data | `GET /sessions/{id}/messages`       |
| end-session      | `DELETE /sessions/{id}`             |
| list-computers   | `GET /computers`                    |
| list-projects    | `GET /projects`                     |
| send-file        | `POST /sessions/{id}/file`          |
| publish          | `POST /api/channels/{name}/publish` |
| channels-list    | `GET /api/channels/`                |

The remaining 14 need new REST endpoints on the daemon API server.

## Success Criteria

- [ ] `telec docs --help` documents the two-phase flow (index vs get by IDs)
- [ ] `telec sessions list` returns JSON session list
- [ ] `telec sessions start --computer local --project /path --title "Test"` creates session
- [ ] `telec sessions send --session-id X --message "hello"` sends message
- [ ] `telec workflow prepare --slug my-item` returns preparation state
- [ ] `telec infra computers` returns computer list
- [ ] `telec infra deploy` triggers deployment
- [ ] `telec delivery result --session-id X --content "done"` sends result
- [ ] `telec channels list` returns active channels
- [ ] `telec --help` shows new subcommand groups alongside existing ones (no `context` group)
- [ ] Every subcommand `--help` has examples covering all parameters
- [ ] Baseline tool `@exec` directives expand correctly in `telec sync`
- [ ] Daemon down → clear error message, non-zero exit code
- [ ] `caller_session_id` injected on every API call
- [ ] Output is valid JSON parseable by agents
- [ ] `telec claude`, `telec gemini`, `telec codex`, `telec list` removed
- [ ] `telec sessions list` replaces `telec list` (sessions belong under `sessions` group)
- [ ] Existing commands (`sync`, `todo`, `init`, `docs`) unaffected

## Constraints

- Extends the existing `telec` CLI — no new binary
- New REST endpoints call the same backend functions MCP handlers use
- Existing REST endpoints and TUI must not regress

## Risks

- Subcommand naming collisions with existing telec commands: audit first
- Large response bodies (session data): must handle correctly
- Some MCP handlers have complex logic (sessions.create with listener
  registration) that needs careful extraction into the REST handler
