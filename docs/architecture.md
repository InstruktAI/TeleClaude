# Architecture Reference

## Project Overview

TeleClaude is a Telegram-to-terminal bridge daemon. From a developer perspective:

**Core Technical Stack:**

- Python 3.11+ async daemon (asyncio-based)
- python-telegram-bot library for Telegram Bot API
- tmux for persistent terminal sessions
- aiosqlite for async session/recording persistence
- Adapter pattern for platform abstraction (enables future WhatsApp, Slack support)

## Component Layers

### Core Layer (`teleclaude/core/`)

- `models.py` - Data classes (Session, Recording) with dict serialization
- `session_manager.py` - Session persistence and SQLite operations
- `terminal_bridge.py` - tmux interaction (create, send keys, capture output, etc.)
- `schema.sql` - Database schema with sessions and recordings tables

### Adapter Layer (`teleclaude/adapters/`)

- `base_adapter.py` - Abstract base class defining adapter interface
- `telegram_adapter.py` - Telegram Bot API implementation
- Future: `whatsapp_adapter.py`, `slack_adapter.py`

### Main Daemon (`teleclaude/daemon.py`)

- `TeleClaudeDaemon` - Main coordinator class
- PID file locking to prevent multiple instances
- Command routing and session lifecycle management
- Output polling with hybrid editing mode

## Key Design Patterns

### Adapter Pattern

All platform-specific code is isolated in adapters. Each adapter implements:

- Lifecycle: `start()`, `stop()`
- Outgoing: `send_message()`, `edit_message()`, `send_file()`
- Channels: `create_channel()`, `update_channel_title()`, `set_channel_status()`
- Callbacks: `on_message()`, `on_file()`, `on_voice()`, `on_command()`

### Session Management

- Sessions are platform-agnostic (core stores adapter_type + adapter_metadata JSON)
- Each session maps to one tmux session
- SQLite stores session state, survives daemon restarts
- Sessions have status: active, idle, disconnected, closed

### Output Streaming

- Hybrid mode: First 5 seconds edit same message, then send new messages
- Poll tmux output every 0.5-2 seconds
- Handle truncation for large outputs (>1000 lines or >100KB)
- Strip ANSI codes and shell prompts (configurable)

## File Management Philosophy

### Session Output Files

- ONE file per active session: `logs/session_output/{session_id[:8]}.txt`
- Persistent (survives daemon restarts) to support downloads after crashes
- Updated every second during polling
- **Deleted when**:
  - Process exits (tmux session dies)
  - Session closed with `/exit` command
- **Never orphaned**: Cleanup in `finally` blocks guarantees deletion

### Temporary Files

- Created ONLY when download button clicked
- Sent immediately to Telegram
- Deleted in `finally` block (robust exception handling)
- **Zero persistent temp files**

### No File Leaks

- `daemon._get_output_file()` - DRY helper for consistent file paths
- `daemon.output_dir` - created once in `__init__`
- All cleanup uses `try/except` to handle failures gracefully

## Output Polling Specification

**Critical Polling Behavior** (daemon.py `_poll_and_send_output`):

1. **Initial delay**: Wait 2 seconds before first poll
2. **Poll interval**: Poll tmux output every 1 second
3. **Hybrid editing mode** (UX optimization):
   - **First 10 seconds**: Edit same Telegram message in-place (clean, live updates)
   - **After 10 seconds**: Send NEW messages with continued output (preserves history)
   - This creates predictable UX: fast commands (< 10s) = single edited message, slow commands = multiple messages
4. **Exit code detection (PRIMARY - ONLY STOP CONDITION)**: Detect when command exits with exit code - stop immediately
   - Append `; echo "__EXIT__$?__"` to every command sent via `send_keys`
   - Parse exit code marker from output
   - Strip marker before showing output to user
   - **This is the ONLY condition that stops polling**
5. **Timeout notification (INFORMATIONAL ONLY)**: If no output change after configured idle timeout (default: 60 seconds, configurable via `polling.idle_notification_seconds`), notify user but KEEP POLLING
   - Send notification as NEW message: "⏸️ No output for {N} seconds - process may be waiting or finished"
   - Do NOT append to existing output - send as separate message
   - If output resumes, automatically delete the notification message (ephemeral notification)
   - **CRITICAL**: This does NOT stop polling - only notifies user
   - Polling continues until exit code is received
6. **Session death detection**: Stop if tmux session no longer exists
7. **Max duration**: Stop after 600 polls (10 minutes)

**DO NOT** use shell prompt detection or string pattern matching. Use explicit exit code markers for reliable command completion detection.

## Output Formatting and Truncation

### Message Format

daemon.py formats, adapter renders:

```sh
Terminal output here (in code block with sh syntax highlighting)
```

⏱️ Running 2m 34s | 📊 145KB | (truncated) | [📎 Download full output button]

**Components:**

1. **Code block**: Terminal output (truncated if needed, showing last ~3400 chars)
2. **Status line** (outside code block, plain text): Running time, output size, truncation indicator, download button
3. **Download button** (Telegram inline keyboard): Appears when output > 3800 chars

### Output Buffer Management

- **In-memory**: `daemon.session_output_buffers[session_id]` stores full output
- **Persistent file**: `logs/session_output/{session_id[:8]}.txt` survives daemon restarts
- **File lifecycle**:
  - Created when polling starts
  - Updated every poll (1s interval)
  - **Survives daemon restarts** (enables downloads after restart)
  - Deleted when:
    - Process exits (tmux session dies)
    - Session closed with `/exit`

### Telegram Truncation & Download

When output exceeds ~3800 chars:

1. Truncate to last ~3400 chars in message
2. Show inline keyboard button: `📎 Download full output`
3. On button click:
   - Read from persistent file (or memory fallback)
   - Create temp file in `/tmp`
   - Send as Telegram document attachment
   - Delete temp file in `finally` block (guaranteed cleanup)
   - **Delete-and-replace**: If clicked again → delete old file message, send new file
   - Only one file message present at a time (clean UI)

### User Message Deletion During Active Polling

When a process is running (polling active):

- User messages sent to session are treated as **input** to the running process
- Messages **automatically deleted** from Telegram after being sent to tmux
- Rationale: Maintains clean UI where last message always shows terminal output
- Tracked via `daemon.active_polling_sessions` set

## Database Operations

- Always use parameterized queries (never string formatting)
- Commit explicitly after writes
- Use `Row` factory for dict-like access
- Foreign keys enabled with ON DELETE CASCADE

## tmux Integration

- Session names: `{computer}-{suffix}` format
- Always check return codes from tmux commands
- Use `-d` flag for detached sessions
- Terminal size set via `-x` and `-y` flags
- Login shell: `{shell} -l` for full environment

## Daemon Management Architecture

### Three-Tier Management System

1. **launchd/systemd** (production): Auto-starts daemon on boot, restarts on crash
2. **daemon-control.sh** (manual): Comprehensive lifecycle management script
3. **Direct Python** (development): `make dev` for foreground testing

**Key Points:**

- launchd should directly invoke Python, NOT a control script (needs to track the actual process for restart)
- Use `make start/stop/restart/status` for daemon management
- Control is handled via launchd (macOS) or systemd (Linux)

**Why this architecture:**

- launchd needs PID visibility for automatic restart (KeepAlive)
- Control script uses nohup which would hide the process from launchd
- Both can coexist: launchd for production, control script for development

### Plist Template System (macOS)

The launchd plist file is generated from a template (`config/ai.instrukt.teleclaude.daemon.plist.template`) during installation. The template uses placeholders:

- `{{PYTHON_PATH}}`: Path to venv Python interpreter
- `{{WORKING_DIR}}`: Project root directory
- `{{PATH}}`: Detected system PATH including Homebrew paths

The plist redirects daemon stdout/stderr to `/dev/null` to prevent launchd issues. tmux sessions get their own PTYs (pseudo-terminals) automatically. CRITICAL: Avoid using `stdout=PIPE, stderr=PIPE` in subprocess calls unless you actually need the output - these pipes can leak to child processes and cause EBADF errors.

## REST API Server

**FastAPI-based REST API runs inside daemon process**

- Default port: 6666 (configurable via `$PORT` environment variable)
- Endpoints:
  - `GET /health` - Health check with uptime and session counts
  - `GET /api/v1/sessions/{session_id}/output` - Dynamic terminal output retrieval
- All output served dynamically from tmux (no static files)
- Used for large output truncation links in Telegram messages

## Architecture Principles

1. **Separation of Concerns**: Core is platform-agnostic, adapters handle platform specifics
2. **Async First**: All I/O is async, blocking operations use thread pools
3. **Fail Fast**: No defensive programming, let errors propagate with context
4. **Explicit Over Implicit**: Config is explicit, no magic defaults
5. **Persistence**: Sessions survive daemon restarts via SQLite + tmux
6. **Stateless Adapters**: All state lives in SessionManager, adapters are thin wrappers
7. **Type Safety**: Full type hints, strict mypy checking
8. **No Hot Reload**: Config loaded once at start, restart daemon to apply changes
9. **Configuration as Source of Truth**: `config.yml` is the single source of truth - code MUST read from config, not environment variables or hardcoded values
10. **Module Organization**: Utilities in `utils.py`, config helpers in dedicated modules, business logic in domain-specific files

## Key Files Reference

### Documentation

- `README.md` - User-facing documentation (installation, configuration, usage)
- `prds/teleclaude.md` - Complete design document and specification
- `docs/troubleshooting.md` - Debugging and troubleshooting guide
- `docs/architecture.md` - This file - technical architecture reference

### Code

- `teleclaude/daemon.py` - Main entry point, daemon lifecycle, command routing
- `teleclaude/core/session_manager.py` - Session CRUD, SQLite operations
- `teleclaude/core/terminal_bridge.py` - tmux wrapper (create, send, capture)
- `teleclaude/adapters/telegram_adapter.py` - Telegram Bot API implementation
- `teleclaude/adapters/base_adapter.py` - Adapter interface definition

### Configuration

- `config.yml.sample` - Configuration template with all options
- `.env.sample` - Environment variables template

## Future Enhancements

### High Priority

- REST API ingress configuration: `ingress.domain` for public HTTPS links to full output
- AI-generated session titles: Use Claude API after N commands
- Live config reload: Watch `config.yml` and reload without daemon restart

### Medium Priority

- Terminal recording: Text + video with configurable rolling window
- Multi-device terminal sizing: Detect device type from Telegram client
- WhatsApp adapter: Extend adapter pattern to support WhatsApp Business API
- Slack adapter: Extend adapter pattern for Slack slash commands

### Nice to Have

- MCP server: Expose TeleClaude as MCP resource for Claude Code integration
- Session templates: Predefined terminal setups (dev, ops, etc.)
- Command aliases: User-configurable shortcuts
