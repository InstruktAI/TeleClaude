# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **For user-facing documentation, installation, and usage instructions, see [README.md](README.md)**

## ⚠️ CRITICAL DEVELOPMENT WORKFLOW ⚠️

**MANDATORY STEPS WHEN WORKING ON TELECLAUDE CODE:**

### 🚨 RULE #0: THE DAEMON MUST NEVER BE DOWN 🚨

**USERS DEPEND ON THIS SERVICE 24/7. DOWNTIME IS NOT ACCEPTABLE.**

- ⚠️ Minimize downtime during development to absolute minimum
- ⚠️ After ANY change, IMMEDIATELY restart the daemon
- ⚠️ ALWAYS verify daemon is running before stepping away
- ⚠️ Use `make restart` for fastest recovery
- ⚠️ If unsure about stability, test in a separate environment first
- ⚠️ Check `make status` after every operation

**The daemon provides critical infrastructure. Treat restarts as production deployments.**

### Development Workflow (KeepAlive Auto-Restart)

**CRITICAL: The service is ALWAYS running (24/7 requirement).** Never manually start the daemon with `python -m teleclaude.daemon` - always use `make` commands.

#### Normal Development Cycle

1. **Make code changes** as needed
2. **Restart daemon**: `make restart`
   - Kills the current PID
   - Service manager (launchd/systemd) auto-restarts it in ~1 second via KeepAlive
3. **Verify**: `make status`
4. **Monitor logs**: `tail -f logs/teleclaude.log`

**Never stop the service to check logs** - use `tail -f` instead.

#### Interactive Debugging (Rare)

Only use `make dev` when you need interactive debugging with breakpoints:

```bash
make stop                    # Stop the service first
make dev                     # Run in foreground (Ctrl+C to stop)
# ... debug interactively ...
make start                   # Re-enable service when done
```

For normal development, **always keep the service running** and use `tail -f logs/teleclaude.log`.

#### Service Lifecycle Management

```bash
make start                   # Start/enable service (after install or manual stop)
make stop                    # Stop/disable service (rarely needed)
make restart                 # Kill PID → auto-restart (~1 sec)
make status                  # Check daemon status and uptime
```

**Only use `make stop`/`make start` for full service lifecycle management** (e.g., disabling service completely). For normal development, just use `make restart`.

#### Troubleshooting Daemon Issues

If the daemon won't start or is crashing immediately, follow these steps:

1. **Unload the service** (disable auto-restart temporarily):
   ```bash
   # macOS
   launchctl unload ~/Library/LaunchAgents/ai.instrukt.teleclaude.daemon.plist

   # Linux
   sudo systemctl stop teleclaude
   ```

2. **Kill any remaining processes**:
   ```bash
   pkill -9 -f teleclaude.daemon
   rm -f teleclaude.pid
   ```

3. **Test daemon startup** (auto-terminates after 5 seconds):
   ```bash
   timeout 5 .venv/bin/python -m teleclaude.daemon 2>&1 | tee /tmp/daemon_test.txt
   ```

   Check the output - if you see "Uvicorn running" and no errors, it works.

4. **If there are errors**, check the captured output:
   ```bash
   cat /tmp/daemon_test.txt
   ```

5. **Once startup works, reload the service**:
   ```bash
   # macOS
   launchctl load ~/Library/LaunchAgents/ai.instrukt.teleclaude.daemon.plist

   # Linux
   sudo systemctl start teleclaude
   ```

6. **Verify it's running**:
   ```bash
   make status
   ```

**NEVER run the daemon in foreground with `make dev` in production - the service must always be up.**

**Common Issues:**
- **"Another daemon instance is already running"**: Kill all processes with `pkill -9 -f teleclaude.daemon` and remove `teleclaude.pid`
- **"This Updater is not running!"**: Telegram adapter failed to start - check bot token in `.env`
- **"Command 'X' is not a valid bot command"**: Telegram commands cannot contain hyphens, use underscores instead
- **Syntax errors**: Run `make lint` to check for Python syntax issues
- **Import errors**: Run `make install` to ensure all dependencies are installed

---

## Project Overview

TeleClaude is a Telegram-to-terminal bridge daemon. From a developer perspective:

**Core Technical Stack:**

- Python 3.11+ async daemon (asyncio-based)
- python-telegram-bot library for Telegram Bot API
- tmux for persistent terminal sessions
- aiosqlite for async session/recording persistence
- Adapter pattern for platform abstraction (enables future WhatsApp, Slack support)

## Installation Workflow

**All installation is managed through make commands:**

1. **`make install`** - Install Python dependencies (creates venv, installs packages)
2. **`make init`** - Run installation wizard that:
   - Detects OS (macOS/Linux)
   - Installs system dependencies (tmux, ffmpeg)
   - Creates `.env` and `config.yml` from templates
   - Prompts for Telegram bot token, user ID, supergroup ID
   - Creates and starts system service (launchd on macOS, systemd on Linux)

**Unattended mode** (for CI/automation):
```bash
# In CI: environment variables already loaded by CI system
# Locally: source .env first if needed
make install && make init ARGS=-y
```

**Never** run `./install.sh` directly - always use `make init`.

## Development Commands

**Quick Reference:** Run `make help` to see all available commands.

### Environment Setup

```bash
make install                 # Install Python dependencies
make init                    # Run installation wizard (interactive)
make init ARGS=-y            # Run in unattended mode
```

### Code Quality

```bash
make format               # Format code (isort + black)
make lint                 # Run linting checks (pylint, mypy)
```

### Testing

```bash
make test-unit            # Run unit tests only
make test-e2e             # Run integration/e2e tests only
make test-all             # Run all tests
make test                 # Alias for test-all
```

### Development

```bash
make dev                  # Run daemon in foreground (Ctrl+C to stop)
make clean                # Clean generated files and caches
```

### Running the Daemon

⚠️ **CRITICAL: Service-Managed Daemon** ⚠️

**If TeleClaude was installed via `make init`, the daemon is managed as a system service.**

**DO NOT manually start the daemon with `python -m teleclaude.daemon`!**

The service (systemd on Linux, launchd on macOS) automatically:

- Starts the daemon on system boot
- Restarts the daemon if it crashes
- Manages logging to `logs/teleclaude.log`

**Service Commands:**

**Linux (systemd):**

```bash
# Check status
sudo systemctl status teleclaude

# Stop service
sudo systemctl stop teleclaude

# Start service
sudo systemctl start teleclaude

# Restart service
sudo systemctl restart teleclaude

# View logs
sudo journalctl -u teleclaude -f

# Disable service (prevent auto-start on boot)
sudo systemctl disable teleclaude
```

**macOS (launchd):**

```bash
# Check status
launchctl list | grep teleclaude

# Stop service
launchctl unload ~/Library/LaunchAgents/ai.instrukt.teleclaude.daemon.plist

# Start service
launchctl load ~/Library/LaunchAgents/ai.instrukt.teleclaude.daemon.plist

# View logs
tail -f logs/teleclaude.log
```

**Killing the Process:**
It is acceptable to kill the daemon process directly (e.g., `kill <PID>`). The service will automatically restart it within 10 seconds.

**Development Mode:**

For interactive debugging with breakpoints:

1. **Stop the service first**: `make stop`
2. **Run in foreground**: `make dev` (runs `python -m teleclaude.daemon`)
3. **Re-enable service when done**: `make start`

**For normal development**, see the Development Workflow section above - keep the service running and use `make restart` for quick restarts.

## Code Architecture

### Component Layers

**Core Layer** (`teleclaude/core/`):

- `models.py` - Data classes (Session, Recording) with dict serialization
- `session_manager.py` - Session persistence and SQLite operations
- `terminal_bridge.py` - tmux interaction (create, send keys, capture output, etc.)
- `schema.sql` - Database schema with sessions and recordings tables

**Adapter Layer** (`teleclaude/adapters/`):

- `base_adapter.py` - Abstract base class defining adapter interface
- `telegram_adapter.py` - Telegram Bot API implementation
- Future: `whatsapp_adapter.py`, `slack_adapter.py`

**Main Daemon** (`teleclaude/daemon.py`):

- `TeleClaudeDaemon` - Main coordinator class
- PID file locking to prevent multiple instances
- Command routing and session lifecycle management
- Output polling with hybrid editing mode

### Key Design Patterns

**Adapter Pattern:**
All platform-specific code is isolated in adapters. Each adapter implements:

- Lifecycle: `start()`, `stop()`
- Outgoing: `send_message()`, `edit_message()`, `send_file()`
- Channels: `create_channel()`, `update_channel_title()`, `set_channel_status()`
- Callbacks: `on_message()`, `on_file()`, `on_voice()`, `on_command()`

**Session Management:**

- Sessions are platform-agnostic (core stores adapter_type + adapter_metadata JSON)
- Each session maps to one tmux session
- SQLite stores session state, survives daemon restarts
- Sessions have status: active, idle, disconnected, closed

**Output Streaming:**

- Hybrid mode: First 5 seconds edit same message, then send new messages
- Poll tmux output every 0.5-2 seconds
- Handle truncation for large outputs (>1000 lines or >100KB)
- Strip ANSI codes and shell prompts (configurable)

## Critical Implementation Rules

### Import Policy

**ALL imports MUST be at the top of files** - `import-outside-toplevel` is enforced by pylint with `--fail-on` flag. NO exceptions.

### Type Hints

- All functions must have type hints (enforced by mypy)
- Use `Optional[T]` for nullable types
- Use `List[T]`, `Dict[K, V]` from `typing` (Python 3.11)

### Async/Await

- All I/O operations are async (database, network, subprocess)
- Use `asyncio.create_subprocess_exec()` for shell commands
- Use `aiosqlite` for database operations
- Proper cleanup with `async with` or explicit `close()`

### Configuration

- Environment variables in `.env` for secrets (tokens, API keys, user IDs)
- YAML config (`config.yml`) for settings (computer name, paths, terminal sizes)
- Environment variable expansion in config: `${VAR}` syntax
- Config loaded once at daemon start (no hot reload in MVP)

### Error Handling

- Use `try/except` for recoverable errors (network, API failures)
- Log errors with `logger.error()` including context
- Return success boolean for operations that can fail
- Retry once for transient failures (Telegram API, Whisper)

### Database Operations

- Always use parameterized queries (never string formatting)
- Commit explicitly after writes
- Use `Row` factory for dict-like access
- Foreign keys enabled with ON DELETE CASCADE

### tmux Integration

- Session names: `{computer}-{suffix}` format
- Always check return codes from tmux commands
- Use `-d` flag for detached sessions
- Terminal size set via `-x` and `-y` flags
- Login shell: `{shell} -l` for full environment

## Testing

### Test Structure

```
tests/
├── unit/           # Fast, isolated tests with mocks
│   └── test_voice.py
└── integration/    # End-to-end tests with real components
    ├── test_core.py
    ├── test_command.py
    ├── test_full_flow.py
    └── ...
```

- Use `pytest` framework with `pytest-asyncio` for async tests
- Test files match `test_*.py` pattern (pytest convention)
- Run all tests: `make test`
- Run unit tests only: `make test-unit`
- Run integration tests only: `make test-e2e`
- Markers available: `@pytest.mark.unit` and `@pytest.mark.integration`

### What to Test

**Unit Tests** (`tests/unit/`):

- Isolated component logic with mocked dependencies
- Voice handler with mocked OpenAI API
- Models and data serialization
- Config parsing and validation

**Integration Tests** (`tests/integration/`):

- Session CRUD operations with real database
- Terminal bridge tmux commands (real tmux sessions)
- Adapter message routing with real daemon components
- End-to-end command flows (cd, cancel, polling)

## Common Development Tasks

## Command Implementation Patterns (Critical!)

### Adding a New Bot Command

When adding a new command to the Telegram bot, you MUST follow ALL these steps:

1. **Register command handler** in `telegram_adapter.py` `start()` method:

   ```python
   self.app.add_handler(CommandHandler("command_name", self._handle_command_name))
   ```

2. **Add to Telegram's command list** in `telegram_adapter.py` `start()` method:

   ```python
   commands = [
       # ... existing commands
       BotCommand("command_name", "Description shown in Telegram UI"),
   ]
   await self.app.bot.set_my_commands(commands)
   ```

   ⚠️ **CRITICAL**: Without this step, the command won't appear in Telegram's autocomplete!

3. **Implement handler method** in `telegram_adapter.py`:

   - ALWAYS use `session = await self._get_session_from_topic(update)` (DRY pattern)
   - Never duplicate authorization/session-finding logic
   - Example:

   ```python
   async def _handle_command_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
       session = await self._get_session_from_topic(update)
       if not session:
           return
       # Your command logic here
   ```

4. **Route command in daemon** (`daemon.py` `handle_command()`):

   ```python
   elif command == "command-name":
       await self._command_name(context, args)
   ```

5. **Implement daemon handler** in `daemon.py`

6. **Update help text** in `_handle_help()` method

### Using Inline Keyboards for User Selections

Pattern for creating clickable button menus (like `/cd` directory selection):

1. **Create inline keyboard**:

   ```python
   keyboard = []
   for item in items:
       keyboard.append([
           InlineKeyboardButton(text=display_text, callback_data=f"action:{data}")
       ])
   reply_markup = InlineKeyboardMarkup(keyboard)
   await update.message.reply_text("Select:", reply_markup=reply_markup)
   ```

2. **Handle button clicks** in `_handle_callback_query()`:

   - Parse `callback_data` as "action:args"
   - Find session from `query.message.message_thread_id`
   - Call `await query.answer()` first
   - Update message with `await query.edit_message_text()`

3. **Register callback handler** in `start()` (already done):
   ```python
   self.app.add_handler(CallbackQueryHandler(self._handle_callback_query))
   ```

### Shell Command Construction Safety

When constructing shell commands that include user input or file paths:

**ALWAYS use `shlex.quote()` to prevent injection and handle special characters:**

```python
import shlex

# CORRECT:
cd_command = f"cd {shlex.quote(user_path)}"

# WRONG (vulnerable to spaces, injection):
cd_command = f"cd {user_path}"
```

This handles:

- Paths with spaces
- Special shell characters (`$`, `;`, `|`, etc.)
- Quote characters

### Adding Config-Driven Features

To add features that use configuration values (like `trustedDirs`):

1. **Add to `config.yml.sample`** with comments and examples
2. **Pass from daemon to adapter** in `telegram_config`:
   ```python
   telegram_config = {
       # ... existing config
       "feature_data": self.config.get("section", {}).get("key", []),
   }
   ```
3. **Store in adapter's `__init__`**:
   ```python
   self.feature_data = config.get("feature_data", [])
   ```
4. **Use in handler methods** as `self.feature_data`

### Adding a New Adapter

1. Create `adapters/{platform}_adapter.py`
2. Inherit from `BaseAdapter`
3. Implement all abstract methods
4. Add adapter initialization in `daemon.py`
5. Update config schema for platform-specific settings

### Modifying Database Schema

1. Update `teleclaude/core/schema.sql`
2. Add migration logic in `SessionManager.initialize()`
3. Test with existing database
4. Update `models.py` if data classes change

### Adding New Configuration Options

1. Add to `config.yml.sample` with comments
2. Document in `prds/teleclaude.md` (design doc)
3. Access via `self.config[key]` in daemon
4. Add validation if required field

## Code Style

### Black + isort

- Line length: 120 characters
- Black profile for isort
- Run `make format` before committing

### Pylint

- Disabled checks: `invalid-name`, `missing-docstring`, `too-few-public-methods`, `too-many-arguments`, `unused-argument`
- ENFORCED check: `import-outside-toplevel` (C0415) with `--fail-on` flag
- All other warnings should be addressed

### Naming Conventions

- Classes: `PascalCase` (e.g., `SessionManager`, `TelegramAdapter`)
- Functions/methods: `snake_case` (e.g., `create_session`, `send_keys`)
- Private methods: `_snake_case` (e.g., `_acquire_lock`, `_emit_message`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_SESSIONS`)
- Async functions: Same as sync, rely on `async def` keyword

### Docstrings

- Use triple quotes for all docstrings
- Function docstrings: brief description + Args + Returns
- Class docstrings: brief description of purpose
- Module docstrings: one-line overview of module purpose

## Key Files Reference

**Documentation:**

- `README.md` - User-facing documentation (installation, configuration, usage)
- `CLAUDE.md` - This file (developer guidance)
- `prds/teleclaude.md` - Complete design document and specification

**Code:**

- `teleclaude/daemon.py` - Main entry point, daemon lifecycle, command routing
- `teleclaude/core/session_manager.py` - Session CRUD, SQLite operations
- `teleclaude/core/terminal_bridge.py` - tmux wrapper (create, send, capture)
- `teleclaude/adapters/telegram_adapter.py` - Telegram Bot API implementation
- `teleclaude/adapters/base_adapter.py` - Adapter interface definition

**Configuration:**

- `config.yml.sample` - Configuration template with all options
- `.env.sample` - Environment variables template

## Architecture Principles

1. **Separation of Concerns**: Core is platform-agnostic, adapters handle platform specifics
2. **Async First**: All I/O is async, blocking operations use thread pools
3. **Fail Fast**: No defensive programming, let errors propagate with context
4. **Explicit Over Implicit**: Config is explicit, no magic defaults
5. **Persistence**: Sessions survive daemon restarts via SQLite + tmux
6. **Stateless Adapters**: All state lives in SessionManager, adapters are thin wrappers
7. **Type Safety**: Full type hints, strict mypy checking
8. **No Hot Reload**: Config loaded once at start, restart daemon to apply changes

## Critical Operational Insights

### Daemon Management Architecture

**Three-Tier Management System:**

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

### REST API Server

**FastAPI-based REST API runs inside daemon process**

- Default port: 6666 (configurable via `$PORT` environment variable)
- Endpoints:
  - `GET /health` - Health check with uptime and session counts
  - `GET /api/v1/sessions/{session_id}/output` - Dynamic terminal output retrieval
- All output served dynamically from tmux (no static files)
- Used for large output truncation links in Telegram messages

### Logging

- Logs to `logs/teleclaude.log`
- Console output only when stdout is a TTY (interactive mode)
- Use `tail -f logs/teleclaude.log` to monitor daemon

**Checking macOS System Logs:**

Use the `/usr/bin/log show` command to check system logs for launchd/daemon errors:

```bash
# Check last 5 minutes for teleclaude mentions (simple grep)
/usr/bin/log show --last 5m --info 2>&1 | grep -i teleclaude

# Check last hour
/usr/bin/log show --last 1h --info 2>&1 | grep -i teleclaude

# Check specific predicate (more targeted, no grep needed)
/usr/bin/log show --predicate 'eventMessage CONTAINS "teleclaude"' --last 10m --info
```

**IMPORTANT**:
- Use `/usr/bin/log` (full path) to avoid conflicts with shell built-ins in Bash
- The `--last` flag takes time units directly (e.g., `5m`, `1h`, `30s`) **without quotes**

### Daemon Control

```bash
make start        # Start daemon
make stop         # Stop daemon
make restart      # Restart daemon
make status       # Check health and uptime
```

## Future Enhancements (See PRDs)

- MCP server for Claude Code integration
- Terminal recording (text + video with 20-minute rolling window)
- Voice message transcription (OpenAI Whisper)
- File upload handling
- AI-generated session titles (Claude API)
- Multi-device terminal sizing
- Quick directory navigation
- Live config reload
