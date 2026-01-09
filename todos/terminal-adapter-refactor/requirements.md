# REST Adapter Refactor

## Problem Statement

Currently the telec CLI uses a separate code path from Telegram:
- telec CLI → HTTP API (FastAPI) → MCP Handlers (direct)
- Telegram → Telegram Adapter → AdapterClient → Daemon Handlers

This bypasses AdapterClient pre/post processing and creates inconsistent behavior.

## Goal

Unify all adapters through AdapterClient. REST Adapter becomes a first-class adapter like Telegram and Redis.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           DAEMON                                 │
│                                                                  │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────────┐ │
│  │ Telegram  │  │   Redis   │  │   REST    │  │     MCP       │ │
│  │  Adapter  │  │  Adapter  │  │  Adapter  │  │    Server     │ │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └───────┬───────┘ │
│        │              │              │                │         │
│        └──────────────┴──────┬───────┘                │         │
│                              ▼                        │         │
│                      ┌───────────────┐                │         │
│                      │ AdapterClient │◄───────────────┘         │
│                      └───────┬───────┘                          │
│                              ▼                                  │
│                      ┌───────────────┐                          │
│                      │    Daemon     │                          │
│                      │   Handlers    │                          │
│                      └───────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
        ▲                      ▲                    ▲
        │                      │                    │
  ┌─────┴─────┐          ┌─────┴─────┐        ┌────┴────┐
  │ Telegram  │          │ telec CLI │        │   AI    │
  └───────────┘          └───────────┘        └─────────┘
```

## Key Principles

1. **All adapters are equal** - Telegram, Redis, REST, MCP all route through AdapterClient
2. **telec CLI is a dumb facade** - Just an HTTP client, no business logic
3. **Adapters normalize input** - Convert transport-specific format to AdapterClient events
4. **Handlers are shared** - Same daemon handlers for all adapters
5. **Presentation is adapter-specific** - Each adapter presents results its own way

## Design Decisions

### D1: Origin Adapter Key
- Rename `"terminal"` to `"rest"` as the origin_adapter value
- Greenfield approach - no backward compatibility with old "terminal" sessions
- All new sessions from telec CLI use `origin_adapter="rest"`

### D2: RESTAdapter Inheritance
- RESTAdapter extends `BaseAdapter` directly (NOT `UiAdapter`)
- It's a transport adapter that:
  - Accepts input (commands, messages via HTTP)
  - Returns results (session_id, tmux_session_name, computer, etc.)
  - Does NOT manage output messages or UI feedback
- telec CLI polls for output separately (via tmux attach or get_session_data)

### D3: Cross-Computer Resume
- Resume commands search ALL computers (local + remote via Redis)
- Returns session info INCLUDING computer name
- telec CLI handles remote access (via SSH) - daemon just returns data
- No proxying through daemon - information only

### D4: Native Session ID Lookup
- Use composite key: `(agent, native_session_id)` for precision
- Query: "WHERE agent = ? AND native_session_id = ?"
- Prevents false matches if different agents have overlapping ID formats

## Requirements

### R1: Rename TerminalAdapter to RESTAdapter
- Rename `adapters/terminal_adapter.py` to `adapters/rest_adapter.py`
- Change `ADAPTER_KEY = "terminal"` to `ADAPTER_KEY = "rest"`
- Absorb `api/routes.py` and `api/server.py` functionality
- Extend `BaseAdapter` (not UiAdapter)
- Delete `api/` directory after merge

### R2: REST Adapter Routes Through AdapterClient
- All HTTP endpoints call `adapter_client.handle_event()`
- Use same event types as Telegram (message, command, etc.)
- Pre/post processing applies to REST requests
- Returns structured results (not just status codes)

### R3: New Resume Commands
Add these commands to daemon handlers (work from all adapters):

#### `/agent_resume <teleclaude-session-id>`
- Lookup session by TeleClaude session_id (local first, then remote via Redis)
- Return session info: `{session_id, tmux_session_name, computer, agent, ...}`
- If not found, return error with clear message

#### `/claude_resume <native-claude-id>`
1. Query all sessions (local + remote) where `agent="claude"` AND `native_session_id="<id>"`
2. If found: return session info `{session_id, tmux_session_name, computer, ...}`
3. If NOT found: create new LOCAL session with `claude --resume <native-id>`
4. Return session info

#### `/gemini_resume <native-gemini-id>`
- Same pattern as /claude_resume but with `agent="gemini"`

#### `/codex_resume <native-codex-id>`
- Same pattern as /claude_resume but with `agent="codex"`

### R4: Database Support for Composite Lookup
- Add method: `get_session_by_agent_and_native_id(agent: str, native_session_id: str)`
- For remote sessions: extend Redis protocol to query by composite key
- Or: fetch all sessions, filter client-side (simpler, acceptable for session counts)

### R5: telec CLI Updates
- Remove direct MCP handler calls
- Use REST API exclusively for all operations
- For resume commands:
  1. Call REST endpoint (e.g., `POST /commands/claude_resume {"native_id": "abc123"}`)
  2. Receive session info in response (includes computer name)
  3. If `computer == local`: attach directly via tmux
  4. If `computer != local`: SSH to remote, attach there
  5. Open TUI with session focused and attached in split pane

### R6: TUI Auto-Focus on Resume
When telec receives session from resume command:
1. Open TUI
2. Expand tree to show that session's project
3. Select that session in the list
4. Open split pane with session attached (local or SSH)
5. Show parent/child relationships if applicable (via initiator_session_id)

### R7: Consistent Command Experience
Same command works identically from:
- Telegram: `/agent_resume abc123` in a topic
- telec CLI: `telec /agent_resume abc123`
- REST API: `POST /commands/agent_resume {"session_id": "abc123"}`

Handler logic is identical. Presentation differs by adapter.

## Use Cases

### UC1: Continue Telegram Session on Laptop
1. User starts session on Telegram (phone)
2. Sees TeleClaude session ID in footer: `📋 tc: abc123-...`
3. At laptop: `telec /agent_resume abc123`
4. TUI opens, tree expands to session, split pane attaches

### UC2: Resume Native Claude Session (Local)
1. User has Claude session ID from previous work: `01JGXYZ...`
2. Runs: `telec /claude_resume 01JGXYZ`
3. Handler searches: no TeleClaude wrapper found
4. Handler creates new session with `claude --resume 01JGXYZ`
5. TUI opens focused on new session, split pane attaches

### UC3: Resume Native Claude Session (Found Remote)
1. User runs: `telec /claude_resume 01JGXYZ`
2. Handler searches: finds session on `workstation` computer
3. Returns: `{session_id: "...", computer: "workstation", tmux_session_name: "tc_xyz"}`
4. telec CLI: SSH to workstation, attach tmux session
5. TUI opens focused on remote session

### UC4: Telegram Resume
1. User presses "Start" button in Telegram (empty session)
2. Sends `/agent_resume abc123` in that topic
3. Handler finds session, returns info
4. Telegram adapter updates topic to show that session's output
5. Same handler, different presentation

## Non-Goals

- No exotic new CLI interfaces
- No additional complexity for users
- No breaking existing `/claude`, `/gemini`, `/codex` quick-start commands
- No backward compatibility with old "terminal" origin_adapter sessions

## Files to Modify

### Core Changes
- `teleclaude/adapters/terminal_adapter.py` → delete (replace with rest_adapter.py)
- `teleclaude/adapters/rest_adapter.py` → NEW: full REST adapter with HTTP server
- `teleclaude/api/routes.py` → delete (absorbed into rest_adapter.py)
- `teleclaude/api/server.py` → delete (absorbed into rest_adapter.py)
- `teleclaude/api/__init__.py` → delete
- `teleclaude/api/models.py` → move to `teleclaude/adapters/rest_models.py`

### Daemon Integration
- `teleclaude/daemon.py` → start RESTAdapter like other adapters, remove api_server task

### Handler Updates
- `teleclaude/core/command_handlers.py` → add resume command handlers

### Database
- `teleclaude/core/db.py` → add `get_session_by_agent_and_native_id()` method

### CLI Updates
- `teleclaude/cli/telec.py` → use REST API, handle remote sessions via SSH
- `teleclaude/cli/tui/app.py` → add auto-focus on resume with session info

## Testing Requirements

- Unit tests for RESTAdapter HTTP endpoints
- Unit tests for resume command handlers
- Integration test: create session via REST, verify routes through AdapterClient
- Integration test: resume by native_session_id (local)
- Integration test: resume by native_session_id (found remote - mock Redis)
