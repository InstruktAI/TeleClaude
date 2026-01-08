# telec: TUI Client for TeleClaude

## Problem Statement

Current `telec` CLI:
1. Only sees sessions on the local computer
2. Uses SQLite polling as IPC mechanism (complex, slow)
3. Limited TUI - just a session picker
4. Can't interact with sessions on remote computers
5. No visibility into AI-to-AI delegation chains

## Goal

Transform `telec` into a rich TUI client that:
1. Connects to the daemon via REST API (Unix socket)
2. Provides a single unified project-centric view
3. Shows AI-to-AI session hierarchies (delegated sessions nested under initiators)
4. Supports remote session attachment via SSH
5. Shows agent availability in persistent footer

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            telec TUI                                     │
│                                                                          │
│  - Connects to REST API socket (/tmp/teleclaude-api.sock)               │
│  - Single unified curses interface                                      │
│  - SSH for remote session attachment                                    │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Daemon REST API (FastAPI)                            │
│                                                                          │
│  GET  /sessions                    - List all sessions                  │
│  GET  /sessions/{id}               - Get session details                │
│  POST /sessions                    - Create new session                 │
│  DELETE /sessions/{id}             - End session                        │
│  POST /sessions/{id}/message       - Send message to session            │
│  GET  /sessions/{id}/transcript    - Get session transcript             │
│  GET  /computers                   - List online computers              │
│  GET  /projects                    - List projects from all computers   │
│  GET  /agents/availability         - Get agent availability status      │
└─────────────────────────────────────────────────────────────────────────┘
```

## TUI Layout

### Project-Centric Unified View

Single view showing computers → projects → sessions in a tree structure.
Sessions with `initiator_session_id` are nested under their parent session.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ macbook                                                          online │
│   ~/apps/TeleClaude                                                     │
│     ├─ [1] claude/slow  "Orchestrate feature"                    5m ago │
│     │    Input: "implement the new auth feature"                        │
│     │    Output: "Delegated to worker for implementation..."            │
│     │                                                                   │
│     │    └─ [1.1] gemini/fast  "Implement auth"                  3m ago │
│     │         Input: "build the auth handler following..."              │
│     │         Output: "Created auth/handler.py with JWT..."             │
│     │                                                                   │
│     └─ [2] claude/slow  "Debug daemon"                           1h ago │
│          Input: "fix the memory leak in the outbox"                     │
│          Output: "Found leak in worker loop, fixed by..."               │
│                                                                         │
│   ~/apps/OtherProject                                                   │
│     └─ (no sessions)                                                    │
│                                                                         │
│ raspi                                                            online │
│   ~/apps/TeleClaude                                                     │
│     └─ [1] claude/slow  "Review PR"                              5m ago │
│          Input: "review the changes in the MCP handler"                 │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│ [Enter] Attach/Start  [n] New  [m] Message  [k] Kill  [t] Transcript    │
├─────────────────────────────────────────────────────────────────────────┤
│ Agents: claude ✓  gemini ✓  codex ✗ (2h 15m)             │ Last: 5s ago│
└─────────────────────────────────────────────────────────────────────────┘
```

### Session Display

Each session shows 2-3 lines:

**Line 1: Identifier**
- Index (hierarchical: 1, 1.1, 1.2, 2, 2.1...)
- Agent/mode
- Title
- Relative time

**Line 2: Last Input**
- Truncated to ~80 characters
- Always present (sessions always start with input)

**Line 3: Last Output** (optional)
- Truncated to ~80 characters
- Only shown if output exists
- Absence of this line indicates session is actively processing

### Color Coding

- Each agent has its own color (claude, gemini, codex each distinct)
- **Bright/normal agent color**: Last activity (the most recent line)
- **Muted/darker agent color**: Previous activity

This indicates state at a glance:
- Input bright, Output muted → session is idle, waiting for input
- Input muted, Output bright → impossible (output always follows input)
- Input bright, no Output line → session is actively processing

### AI-to-AI Session Hierarchy

Sessions are nested based on `initiator_session_id`:
- If session B was started by session A, B appears nested under A
- Index numbering reflects hierarchy: parent `[1]`, children `[1.1]`, `[1.2]`
- Enables visualization of orchestrator → worker delegation chains

### Computer Display

- Only online computers are shown
- Offline computers are hidden entirely
- No health stats (CPU/mem/disk) - just online/offline status

### Navigation

- `↑/↓` or arrow keys - Navigate between items
- `Tab` - Move between sections
- `Enter` - Context-sensitive action (attach to session, start session on empty project)

### Action Bar

Shown at bottom, actions apply to selected item:
- `Enter` - Attach to session / Start session (on project with no sessions)
- `n` - New session (opens modal)
- `m` - Send message to selected session
- `k` - Kill/end selected session
- `t` - View transcript
- `r` - Refresh

### Persistent Footer

- Agent availability: `✓` = available, `✗ (Xh Ym)` = unavailable with countdown
- Last refresh timestamp

## Start Session Modal

```
┌─ Start Session ─────────────────────────────────────────┐
│                                                          │
│  Computer:  raspi                                        │
│  Project:   ~/apps/TeleClaude                           │
│                                                          │
│  ┌─ Agent ──────────────────────────────────────────┐   │
│  │  ● claude    ○ gemini    ░ codex (2h 15m)        │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─ Mode ───────────────────────────────────────────┐   │
│  │  ○ fast    ● slow    ○ med                       │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  Prompt:                                                 │
│  ┌──────────────────────────────────────────────────┐   │
│  │ _                                                 │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  [Enter] Start    [Esc] Cancel                          │
└──────────────────────────────────────────────────────────┘
```

### Unavailable Agent Handling

- Unavailable agents are grayed out with countdown: `░ codex (2h 15m)`
- Arrow keys skip over unavailable agents (cannot be selected)
- Prevents users from attempting to start sessions with rate-limited agents

### Navigation

- `↑/↓` - Move between field groups
- `←/→` - Select within a group (skips unavailable agents)
- `Tab` - Move between groups
- `Enter` - Start session
- `Esc` - Cancel

## Functional Requirements

### FR-1: REST API Communication

Connect to daemon via Unix socket (`/tmp/teleclaude-api.sock`).

**On startup:**
1. Connect to API socket
2. Fetch sessions, computers, projects, agent availability
3. Build unified tree view

### FR-2: Session Attachment

**Local session:**
```bash
tmux attach -t <tmux_session_name>
```

**Remote session:**
```bash
ssh -t <user>@<host> "tmux attach -t <tmux_session_name>"
```

### FR-3: Agent Availability

- Read on startup, display in footer
- Unavailable agents disabled in start modal (grayed out, not selectable)
- Footer: `✓` = available, `✗ (Xh Ym)` = unavailable with countdown

### FR-4: CLI Shortcuts

```bash
telec                          # Open TUI
telec /list                    # List sessions (stdout, no TUI)
telec /claude [mode] [prompt]  # Start Claude session
telec /gemini [mode] [prompt]  # Start Gemini session
telec /codex [mode] [prompt]   # Start Codex session
```

## Non-Functional Requirements

### NFR-1: Performance
- Startup: < 1s to first render
- API call timeout: 5s

### NFR-2: Terminal Compatibility
- Minimum: 80x24
- Scales to larger terminals
- Color support (degrade gracefully)
- Works inside tmux

### NFR-3: Navigation
- Full keyboard navigation (arrows + Tab)
- Consistent keybindings throughout

## Dependencies

- **db-refactor** - provides `last_input`, `last_output` columns
- Daemon running with REST API enabled
- SSH keys configured for remote computers

## Success Criteria

- [ ] TUI displays unified project-centric tree view
- [ ] Sessions nested under their projects
- [ ] AI-to-AI sessions nested under initiator sessions
- [ ] Session lines show last input/output with color coding
- [ ] Footer shows agent availability
- [ ] Can attach to local sessions via tmux
- [ ] Can attach to remote sessions via SSH
- [ ] Start session modal with agent/mode selection
- [ ] Unavailable agents disabled in modal
- [ ] All navigation works with keyboard
- [ ] CLI shortcuts work (`/list`, `/claude`, `/gemini`, `/codex`)
