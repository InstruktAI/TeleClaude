# Terminal Adapter Refactor to REST Adapter

## Problem Statement

Currently the telec CLI uses a separate code path from Telegram:
- telec CLI → HTTP API (FastAPI) → MCP Handlers (direct)
- Telegram → Telegram Adapter → AdapterClient → Daemon Handlers

This bypasses AdapterClient pre/post processing and creates inconsistent behavior.

## Goal

Unify all adapters through AdapterClient. REST Adapter becomes a first-class adapter like Telegram, Redis.

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

## Requirements

### R1: Rename TerminalAdapter to RESTAdapter
- Move from `adapters/terminal_adapter.py` to `adapters/rest_adapter.py`
- Absorb current `api/routes.py` and `api/server.py` functionality
- Implement as BaseAdapter subclass with HTTP server

### R2: REST Adapter Routes Through AdapterClient
- All HTTP endpoints call `adapter_client.handle_event()`
- Use same event types as Telegram (message, command, etc.)
- Pre/post processing applies to REST requests

### R3: New Commands
Add these commands to daemon handlers (work from all adapters):

- `/agent_resume <teleclaude-session-id>` - Resume by TeleClaude ID
  - Lookup session by ID
  - Return session info (session_id, tmux_session_name, etc.)
  - If not found, return error

- `/claude_resume <native-claude-id>` - Resume by native Claude session ID
  - Lookup: does TeleClaude session exist wrapping this native ID?
  - YES: return that session
  - NO: create new TeleClaude session, start Claude with `--resume <native-id>`
  - Return session info

- `/gemini_resume <native-gemini-id>` - Same pattern for Gemini
- `/codex_resume <native-codex-id>` - Same pattern for Codex

### R4: telec CLI Updates
- Remove direct MCP handler calls
- Use REST API exclusively
- For resume commands:
  1. Call REST endpoint
  2. Receive session info in response
  3. Open TUI with session focused and attached in split pane

### R5: TUI Auto-Focus on Resume
When telec receives session from resume command:
1. Open TUI
2. Expand tree to show that session
3. Select that session
4. Open split pane with session attached
5. Show parent/child relationships if applicable

### R6: Consistent Command Experience
Same command works identically from:
- Telegram: `/agent_resume abc123` in a topic
- telec CLI: `telec /agent_resume abc123`
- REST API: `POST /commands/agent_resume {"session_id": "abc123"}`

Handler logic is identical. Presentation differs by adapter.

## Use Cases

### UC1: Continue Telegram Session on Laptop
1. User starts session on Telegram (phone)
2. Sees TeleClaude session ID in footer
3. At laptop: `telec /agent_resume <id>`
4. TUI opens focused on that session, attached

### UC2: Resume Native Claude Session
1. User was in Claude session, knows native session ID
2. Runs: `telec /claude_resume <native-id>`
3. TeleClaude wraps or finds existing wrapper
4. TUI opens focused on session

### UC3: Telegram Resume
1. User presses "Start" button in Telegram (empty session)
2. Sends `/agent_resume abc123` in that topic
3. That topic now shows session abc123's output
4. Same handler, different presentation

## Non-Goals

- No exotic new CLI interfaces
- No additional complexity for users
- No breaking existing `/claude`, `/gemini`, `/codex` quick-start commands

## Files to Modify

- `teleclaude/adapters/terminal_adapter.py` → rename/refactor to `rest_adapter.py`
- `teleclaude/api/routes.py` → merge into REST adapter
- `teleclaude/api/server.py` → merge into REST adapter
- `teleclaude/daemon.py` → add new handlers, start REST adapter like others
- `teleclaude/cli/telec.py` → update to use new resume commands
- `teleclaude/cli/tui/app.py` → add auto-focus on resume
