# telec-mcp: TUI Client for TeleClaude MCP

## Problem Statement

Current `telec` CLI:
1. Only sees sessions on the local computer
2. Uses SQLite `terminal_outbox` as IPC mechanism (polling-based, complex)
3. Limited TUI - just a session picker
4. Can't interact with sessions on remote computers

Users want a unified view of all sessions across all computers, like Telegram provides.

## Goal

Transform `telec` into a rich TUI client that:
1. Connects to the local MCP server via Unix socket
2. Uses existing MCP tools for cross-computer visibility
3. Provides rich session management interface
4. Supports remote session attachment via SSH

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            telec TUI                                     │
│                                                                          │
│  - Connects to local MCP socket (/tmp/teleclaude-mcp.sock)              │
│  - Calls existing MCP tools                                             │
│  - Rich curses-based interface                                          │
│  - SSH for remote session attachment                                    │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     MCP Server (local daemon)                            │
│                                                                          │
│  teleclaude__list_sessions()     - All sessions, all computers          │
│  teleclaude__list_computers()    - Available computers                  │
│  teleclaude__list_projects()     - Projects per computer                │
│  teleclaude__start_session()     - Create new session                   │
│  teleclaude__send_message()      - Send to existing session             │
│  teleclaude__get_session_data()  - Get session transcript               │
│  teleclaude__end_session()       - Terminate session                    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Functional Requirements

### FR-1: Session Listing (All Computers)

Display all sessions from all computers in a unified view.

**Data per session:**
- Computer name
- Session ID (truncated)
- Title
- Active agent (claude/gemini/codex/—)
- Thinking mode (fast/med/slow)
- Agent status (idle/thinking/waiting - if available)
- Last activity timestamp
- Last message sent (truncated)
- Last feedback received (truncated)

**Sorting:**
- Default: by last_activity descending (most recent first)
- Optional: by computer, by agent

**Filtering:**
- By computer name
- By agent type
- By title/session_id (search)

### FR-2: Session Attachment

**Local session:**
```bash
tmux attach -t <tmux_session_name>
```

**Remote session:**
```bash
ssh -t <user>@<host> "tmux attach -t <tmux_session_name>"
```

Computer connection info comes from `teleclaude__list_computers()` which returns `user`, `host` per computer.

### FR-3: New Session Creation

Create sessions via MCP:
- Select computer (default: local)
- Select project directory (via `teleclaude__list_projects()`)
- Select agent (claude/gemini/codex)
- Select thinking mode (fast/med/slow)
- Optional: initial prompt

Uses `teleclaude__start_session()`.

### FR-4: Session Actions

From the TUI, user can:
- **Attach** - connect to tmux (local or SSH)
- **Send message** - via `teleclaude__send_message()`
- **Kill/End** - via `teleclaude__end_session()`
- **View transcript** - via `teleclaude__get_session_data()`
- **Refresh** - reload session list

### FR-5: Agent Shortcuts

Preserve current telec convenience commands:
- `telec /claude [mode] [prompt]` - start Claude session
- `telec /gemini [mode] [prompt]` - start Gemini session
- `telec /codex [mode] [prompt]` - start Codex session
- `telec /agent <name> <mode> [prompt]` - generic agent start

These now go through MCP instead of terminal_outbox.

### FR-6: Rich TUI Display

```
┌─ TeleClaude Sessions ──────────────────────────────────────────────────────┐
│ Computer   Idx  Agent   Mode  Status     Last Activity   Title             │
├─────────────────────────────────────────────────────────────────────────────┤
│ macbook     1   claude  slow  thinking   2m ago          Debug auth flow   │
│   ├─ Sent: "check the login handler"                                       │
│   └─ Feedback: "I found the issue in auth/handler.py:45..."                │
│                                                                            │
│ raspi       2   gemini  med   idle       15m ago         Refactor daemon   │
│   ├─ Sent: "/compact"                                                      │
│   └─ Feedback: "Context compacted. Ready for next task."                   │
│                                                                            │
│ macbook     3   —       —     idle       1h ago          (untitled)        │
│   └─ (no recent activity)                                                  │
└────────────────────────────────────────────────────────────────────────────┘
  [Enter] Attach  [n] New  [m] Message  [k] Kill  [t] Transcript  [/] Filter  [r] Refresh  [q] Quit
```

### FR-7: Offline/Fallback Mode

If MCP socket unavailable:
- Fall back to local SQLite view (current behavior)
- Display warning: "MCP unavailable - showing local sessions only"

## Non-Functional Requirements

### NFR-1: MCP Communication

- Connect via Unix socket (no HTTP)
- Use JSON-RPC protocol (MCP standard)
- Handle connection failures gracefully
- Timeout: 5s for MCP calls

### NFR-2: Performance

- Session list refresh: < 500ms
- TUI responsive during MCP calls (async)
- Don't block on slow remote computers

### NFR-3: Terminal Compatibility

- Works in standard 80x24 terminal
- Scales to larger terminals
- Color support (optional, degrade gracefully)
- Works inside tmux

## Dependencies

- **db-refactor** (recommended first) - adds `last_message_sent`, `last_feedback_received` columns
- MCP server running locally
- SSH access configured for remote computers (keys in agent)

## Out of Scope

- Web UI (this is terminal-only)
- Direct Redis communication (goes through MCP)
- Session migration between computers
- Real-time streaming updates (polling-based refresh)

## Migration

### terminal_outbox Deprecation

Once telec uses MCP:
1. `terminal_outbox` table becomes unused
2. `_terminal_outbox_worker()` in daemon.py becomes dead code
3. Can be removed after telec-mcp is stable

### Backward Compatibility

- Keep old `telec` commands working during transition
- `telec` (no args) → TUI picker (new)
- `telec /list` → list via MCP (updated)
- `telec /claude ...` → start via MCP (updated)

## Success Criteria

- [ ] telec shows sessions from all computers
- [ ] Can attach to local sessions via tmux
- [ ] Can attach to remote sessions via SSH
- [ ] Can create new sessions on any computer
- [ ] Can send messages to existing sessions
- [ ] Can kill sessions
- [ ] TUI displays last_message_sent and last_feedback_received
- [ ] Falls back gracefully when MCP unavailable
- [ ] terminal_outbox code can be removed
