# telec: TUI Client for TeleClaude

## Problem Statement

Current `telec` CLI:
1. Only sees sessions on the local computer
2. Uses SQLite polling as IPC mechanism (complex, slow)
3. Limited TUI - just a session picker
4. Can't interact with sessions on remote computers
5. No visibility into AI-to-AI delegation chains
6. No visibility into planned work (todos/roadmap)

## Goal

Transform `telec` into a rich TUI client that:
1. Connects to the daemon via REST API (Unix socket)
2. Provides two views: Sessions (running work) and Preparation (planned work)
3. Shows AI-to-AI session hierarchies (delegated sessions nested under initiators)
4. Shows todos with their status and allows starting/preparing work
5. Supports remote session attachment via SSH
6. Shows agent availability in persistent footer

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            telec TUI                                     │
│                                                                          │
│  - Connects to REST API socket (/tmp/teleclaude-api.sock)               │
│  - Two views: Sessions (1) and Preparation (2)                          │
│  - SSH for remote session attachment                                    │
│  - glow for markdown viewing, $EDITOR for editing                       │
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
│  GET  /projects/{path}/todos       - List todos for a project           │
│  GET  /agents/availability         - Get agent availability status      │
└─────────────────────────────────────────────────────────────────────────┘
```

## View Navigation

Two views, switchable via number keys:

- `1` - Sessions view (running work)
- `2` - Preparation view (planned work)

Both views share the same tree structure: Computer → Project → Items

---

## View 1: Sessions

### Project-Centric Unified View

Shows computers → projects → sessions in a tree structure.
Sessions with `initiator_session_id` are nested under their parent session.

```
┌─ [1] Sessions  [2] Preparation ─────────────────────────────────────────┐
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
- Input bright, no Output line → session is actively processing

### AI-to-AI Session Hierarchy

Sessions are nested based on `initiator_session_id`:
- If session B was started by session A, B appears nested under A
- Index numbering reflects hierarchy: parent `[1]`, children `[1.1]`, `[1.2]`
- Enables visualization of orchestrator → worker delegation chains

### Sessions Action Bar

- `Enter` - Attach to session / Start session (on project with no sessions)
- `n` - New session (opens modal)
- `m` - Send message to selected session
- `k` - Kill/end selected session
- `t` - View transcript
- `r` - Refresh

---

## View 2: Preparation

### Todo-Centric View

Shows computers → projects → todos from `todos/roadmap.md`.
Flat list (no dependency nesting - dependencies are managed conversationally by AI).

```
┌─ [1] Sessions  [2] Preparation ─────────────────────────────────────────┐
│ macbook                                                          online │
│   ~/apps/TeleClaude                                                     │
│     ├─ [ ] test-cleanup                                         pending │
│     │    Define and enforce test quality standards                      │
│     │    requirements: ✗  impl-plan: ✗                                  │
│     │                                                                   │
│     ├─ [.] ui-event-queue-per-adapter                             ready │
│     │    Create per-adapter UI event queues                             │
│     │    requirements: ✓  impl-plan: ✓                                  │
│     │                                                                   │
│     ├─ [>] db-refactor                                      in progress │
│     │    Eliminate ux_state JSON blob                                   │
│     │    requirements: ✓  impl-plan: ✓                                  │
│     │                                                                   │
│     └─ [.] telec-enhancements                                     ready │
│          Transform telec into rich TUI                                  │
│          requirements: ✓  impl-plan: ✓                                  │
│                                                                         │
│ raspi                                                            online │
│   ~/apps/TeleClaude                                                     │
│     └─ (same todos - shared repo)                                       │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│ [s] Start Work  [p] Prepare  [v/V] View  [e/E] Edit  [r] Refresh        │
├─────────────────────────────────────────────────────────────────────────┤
│ Agents: claude ✓  gemini ✓  codex ✗ (2h 15m)             │ Last: 5s ago│
└─────────────────────────────────────────────────────────────────────────┘
```

### Todo Display

Each todo shows 3 lines:

**Line 1: Status and Slug**
- Status indicator: `[ ]` pending, `[.]` ready, `[>]` in progress
- Slug name
- Status label (pending/ready/in progress)

**Line 2: Description**
- From roadmap.md (text after the slug line)
- Truncated to ~80 characters

**Line 3: File Status**
- `requirements: ✓/✗` - whether requirements.md exists
- `impl-plan: ✓/✗` - whether implementation-plan.md exists

### Todo Parsing

Todos are parsed from `todos/roadmap.md`:

```markdown
- [ ] slug-name
      Description text here
```

Pattern: `^-\s+\[([ .>])\]\s+(\S+)` extracts status and slug.
Description is the indented text following the slug line.

### Preparation Action Bar

- `s` - Start Work: Run `/prime-orchestrator {slug}` (only for `[.]` ready items)
- `p` - Prepare: Run `/next-prepare {slug}` (any status)
- `v` - View requirements.md (opens in `glow`)
- `V` - View implementation-plan.md (opens in `glow`)
- `e` - Edit requirements.md (opens in `$EDITOR`)
- `E` - Edit implementation-plan.md (opens in `$EDITOR`)
- `r` - Refresh

### External Tool Integration

**Viewing markdown (glow):**
```python
curses.endwin()  # Suspend TUI
subprocess.run(["glow", f"todos/{slug}/requirements.md"])
curses.doupdate()  # Resume TUI
```

**Editing files ($EDITOR):**
```python
curses.endwin()
editor = os.environ.get("EDITOR", "vim")
subprocess.run([editor, f"todos/{slug}/requirements.md"])
curses.doupdate()
```

### Action Availability

| Action | Available when |
|--------|----------------|
| Start Work (`s`) | Status is `[.]` (ready) AND requirements.md exists AND impl-plan.md exists |
| Prepare (`p`) | Always |
| View requirements (`v`) | requirements.md exists |
| View impl-plan (`V`) | implementation-plan.md exists |
| Edit requirements (`e`) | Always (creates if missing) |
| Edit impl-plan (`E`) | Always (creates if missing) |

---

## Shared Components

### Computer Display

- Only online computers are shown
- Offline computers are hidden entirely
- No health stats (CPU/mem/disk) - just online/offline status

### Navigation

- `1` / `2` - Switch views
- `↑/↓` or arrow keys - Navigate between items
- `Tab` - Move between sections
- `Enter` - Context-sensitive action
- `r` - Refresh current view

### Persistent Footer

- Agent availability: `✓` = available, `✗ (Xh Ym)` = unavailable with countdown
- Last refresh timestamp

---

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

### Modal Navigation

- `↑/↓` - Move between field groups
- `←/→` - Select within a group (skips unavailable agents)
- `Tab` - Move between groups
- `Enter` - Start session
- `Esc` - Cancel

---

## Functional Requirements

### FR-1: REST API Communication

Connect to daemon via Unix socket (`/tmp/teleclaude-api.sock`).

**On startup:**
1. Connect to API socket
2. Fetch sessions, computers, projects, agent availability
3. Build unified tree view for current view

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

### FR-4: Todo Parsing

- Parse `todos/roadmap.md` for slug, status, description
- Check file existence: `todos/{slug}/requirements.md`, `todos/{slug}/implementation-plan.md`
- No dependency parsing (handled conversationally by AI)

### FR-5: External Tool Launch

- Suspend TUI with `curses.endwin()`
- Launch external tool (glow, $EDITOR, tmux attach, ssh)
- Resume TUI with `curses.doupdate()` when tool exits

### FR-6: CLI Shortcuts

```bash
telec                          # Open TUI (Sessions view)
telec /list                    # List sessions (stdout, no TUI)
telec /claude [mode] [prompt]  # Start Claude session
telec /gemini [mode] [prompt]  # Start Gemini session
telec /codex [mode] [prompt]   # Start Codex session
```

---

## Non-Functional Requirements

### NFR-1: Performance
- Startup: < 1s to first render
- View switch: < 200ms
- API call timeout: 5s

### NFR-2: Terminal Compatibility
- Minimum: 80x24
- Scales to larger terminals
- Color support (degrade gracefully)
- Works inside tmux

### NFR-3: Navigation
- Full keyboard navigation (arrows + Tab + number keys)
- Consistent keybindings across views

### NFR-4: External Dependencies
- `glow` for markdown viewing (graceful degradation if missing)
- `$EDITOR` for file editing (fallback to `vim`)

---

## Dependencies

- **db-refactor** - provides `last_input`, `last_output` columns
- Daemon running with REST API enabled
- SSH keys configured for remote computers
- `glow` installed for markdown viewing (optional but recommended)

---

## Success Criteria

### Sessions View
- [ ] TUI displays unified project-centric tree view
- [ ] Sessions nested under their projects
- [ ] AI-to-AI sessions nested under initiator sessions
- [ ] Session lines show last input/output with color coding
- [ ] Can attach to local sessions via tmux
- [ ] Can attach to remote sessions via SSH
- [ ] Start session modal with agent/mode selection
- [ ] Unavailable agents disabled in modal

### Preparation View
- [ ] Todos parsed from roadmap.md
- [ ] Todo lines show status, description, file existence
- [ ] Start Work action launches orchestrator (ready items only)
- [ ] Prepare action launches architect session
- [ ] View actions open glow for markdown rendering
- [ ] Edit actions open $EDITOR

### Shared
- [ ] View switching with `1` / `2` keys
- [ ] Footer shows agent availability
- [ ] All navigation works with keyboard
- [ ] CLI shortcuts work (`/list`, `/claude`, `/gemini`, `/codex`)
