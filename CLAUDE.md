# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **For user-facing documentation, installation, and usage instructions, see [README.md](README.md)**

## 🚨 CRITICAL RULES (Never Break These)

### Rule #0: THE DAEMON MUST NEVER BE DOWN

**USERS DEPEND ON THIS SERVICE 24/7. DOWNTIME IS NOT ACCEPTABLE.**

- Minimize downtime during development to absolute minimum
- After ANY change, IMMEDIATELY restart the daemon with `make restart`
- ALWAYS verify daemon is running before stepping away with `make status`
- If unsure about stability, test in a separate environment first
- The daemon provides critical infrastructure - treat restarts as production deployments

### Rule #0.5: AUTOMATED DEPLOYMENT WORKFLOW

**AFTER COMMITTING CHANGES, ALWAYS DEPLOY TO ALL MACHINES USING THE MCP TOOL.**

When you've made changes that should be deployed:

1. **Commit changes locally** (using `/commit` command with proper message format)
2. **Push to GitHub**: `git push`
3. **Deploy to all machines**: Use `teleclaude__deploy_to_all_computers` MCP tool
   - This will automatically:
     - Send deploy command to all remote computers (RasPi, RasPi4, etc.)
     - Each computer will: `git pull` → restart daemon via service manager
     - Wait for deployment completion (max 60 seconds per computer)
     - Return status for each machine (deployed, error, timeout)

**Example workflow:**
```
User: "Deploy these changes to all machines"

Claude:
1. Uses teleclaude__deploy_to_all_computers() [NO ARGUMENTS]
2. Tool automatically discovers ALL computers and deploys
3. Reports: "Deployed to RasPi (PID 123456), RasPi4 (PID 789012)"
```

**DO NOT** manually SSH to each machine anymore - the MCP tool handles this automatically via Redis.

### Rule #1: SINGLE DATABASE ONLY

**THERE IS ONLY ONE DATABASE FILE: `teleclaude.db` IN PROJECT ROOT.**

- NEVER create additional database files
- NEVER copy or duplicate the database
- Database path is configured in `config.yml`: `${WORKING_DIR}/teleclaude.db`
- If you find multiple `.db` files, DELETE the extras immediately
- Any code that creates a new database file is a CRITICAL BUG

### Rule #2: PROPER TEST STRUCTURE ONLY

**NEVER create ad-hoc test scripts or one-off testing files!**

- ❌ NO standalone test scripts (e.g., `test_something.py` in project root)
- ❌ NO temporary test files for quick validation
- ❌ NO `if __name__ == "__main__"` test runners outside of `tests/` directory
- ✅ ONLY create tests in the proper `tests/unit/` or `tests/integration/` directories
- ✅ ONLY use pytest framework with proper fixtures and markers
- ✅ ALL tests must be runnable via `make test`, `make test-unit`, or `make test-e2e`

### Rule #3: CODE ORGANIZATION

**YOU WILL BE REVIEWED BY WORLD-CLASS ENGINEERS. FOLLOW THESE RULES WITHOUT EXCEPTION.**

1. **File Size Limit: 500 lines maximum** - Extract code into separate modules if exceeded
2. **Extract Utilities to Separate Files** - Utility functions NEVER belong in class files
3. **Class Cohesion** - Classes should only contain methods related to their core responsibility
4. **Module-Level Functions vs Class Methods** - If it's not using `self`, it doesn't belong in the class
5. **Single Responsibility Principle** - Each module, class, and function does ONE thing

**🚨 ANTI-PATTERN CHECKLIST - STOP if you're about to write:**

- `thing.thing = ...` → Creating confusing double references (session_manager.session_manager, db.db)
- `self.something_manager = ...` → Should be module-level import instead
- Passing singletons as parameters → Use `from module import singleton` instead
- Three+ lines to access a singleton → Should be one import line
- `def __init__(self, x, y, z, a, b, c):` → Too many dependencies, use module-level imports

**First-principles question:** "Would a junior dev understand this in 5 seconds?" If no, simplify.

### Rule #4: IMPORT POLICY

**ALL imports MUST be at the top of files** - `import-outside-toplevel` is enforced by pylint with `--fail-on` flag. NO exceptions.

### Rule #5: TEST EXECUTION POLICY

**NEVER manually wait for tests. Just run `make test`.**

- ❌ NO `sleep` or manual waits for test results
- ❌ NO `asyncio.sleep()` in tests (use deterministic sync)
- ✅ Pytest handles timeouts (5s per test, configured in pyproject.toml)
- ✅ Total test suite: <10 seconds (unit <1s, integration <5s)
- ✅ If tests timeout, fix the test - don't wait longer

## Essential Development Workflow

### Normal Development Cycle

The service is ALWAYS running (24/7 requirement). Never manually start the daemon with `python -m teleclaude.daemon` - always use `make` commands.

1. **Make code changes** as needed
2. **Restart daemon**: `make restart`
   - Kills the current PID
   - Service manager (launchd/systemd) auto-restarts it in ~1 second via KeepAlive
3. **Verify**: `make status`
4. **Monitor logs**: `tail -f /var/log/teleclaude.log`

**Never stop the service to check logs** - use `tail -f` instead.

### Interactive Debugging (Rare)

Only use `make dev` when you need interactive debugging with breakpoints:

```bash
make stop                    # Stop the service first
make dev                     # Run in foreground (Ctrl+C to stop)
# ... debug interactively ...
make start                   # Re-enable service when done
```

For normal development, **always keep the service running** and use `tail -f /var/log/teleclaude.log`.

### Service Lifecycle Commands

```bash
make start                   # Start/enable service (after install or manual stop)
make stop                    # Stop/disable service (rarely needed)
make restart                 # Kill PID → auto-restart (~1 sec)
make status                  # Check daemon status and uptime
```

**Only use `make stop`/`make start` for full service lifecycle management** (e.g., disabling service completely). For normal development, just use `make restart`.

### When Things Break

@docs/troubleshooting.md

## Quick Command Reference

### Environment Setup

```bash
make install                 # Install Python dependencies
make init                    # Run installation wizard (interactive)
make init ARGS=-y            # Run in unattended mode
```

### Code Quality

```bash
make format                  # Format code (isort + black)
make lint                    # Run linting checks (pylint, mypy)
```

### Testing

```bash
make test-unit               # Run unit tests only
make test-e2e                # Run integration/e2e tests only
make test-all                # Run all tests
make test                    # Alias for test-all
```

### Development

```bash
make dev                     # Run daemon in foreground (Ctrl+C to stop)
make clean                   # Clean generated files and caches
```

## Testing Requirements for Code Changes

**Before reporting completion of ANY code change:**

1. Add proper test case in `tests/unit/` or `tests/integration/`
2. Run `make test-unit` or `make test-e2e` to verify tests pass
3. Only report "Done" after automated tests pass
4. ❌ **NEVER rely on manual inspection** - write automated tests instead

## Command Implementation Patterns

### Clean UX Rule for Telegram Adapter

**CRITICAL**: Telegram adapter (`has_ui=True`) follows strict message management rules for clean UX:

**Output Messages (from terminal commands):**
- **ALWAYS EDITED**, never create new messages
- One persistent message per session output
- Message ID stored in `ux_state` (session table)
- Survives daemon restarts

**Feedback Messages (status/info):**
- **ALWAYS TEMPORARY**, deleted when new input arrives
- Examples: "Transcribing...", "Changed directory to...", "Session created"
- Message IDs stored in `ux_state.pending_deletions`
- Auto-deleted by message handler before processing next input

**System Messages (heartbeats, registry):**
- **ALWAYS EDITED**, never create new messages after initial post
- Message ID stored in `system_settings` table (system UX state)
- Examples: `[REGISTRY] {computer} last seen at...`
- Survives daemon restarts via `SystemUXState.registry_message_id`

**Implementation:**
- All message IDs persisted in `ux_state` column (JSON)
- `update_session_ux_state()` / `update_system_ux_state()` functions
- Load state on startup, edit existing messages instead of creating new ones

### Master Bot Pattern (Multi-Computer Setup)

**CRITICAL DESIGN PATTERN for multi-computer deployments:**

When running TeleClaude on multiple computers with different bots in the same Telegram supergroup, **ONLY the master computer registers Telegram commands**. This prevents duplicate command entries in Telegram's UI.

**Configuration:**

```yaml
# config.yml on master computer
telegram:
  is_master: true  # This bot registers commands

# config.yml on non-master computers
telegram:
  is_master: false  # These bots clear their command lists
```

**Trailing Space Pattern:**

BotCommand definitions **intentionally include trailing spaces**:

```python
commands = [
    BotCommand("new_session ", "Create a new terminal session"),  # Note the trailing space
    BotCommand("list_sessions ", "List all active sessions"),
]
```

**Why trailing spaces?**

- Without trailing space: Telegram appends `@botname` in autocomplete → `"/new_session@masterbot"`
- With trailing space: Commands are distributed to ALL bots → `"/new_session "` works for any bot
- Prevents duplicate command entries when multiple bots are in the same group
- Users can type commands without specifying which bot to use

**DO NOT remove trailing spaces from BotCommand definitions** - this is intentional, not a bug!

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
       BotCommand("command_name ", "Description shown in Telegram UI"),  # Note trailing space!
   ]
   await self.app.bot.set_my_commands(commands)
   ```

   ⚠️ **CRITICAL**: Without this step, the command won't appear in Telegram's autocomplete!
   ⚠️ **IMPORTANT**: Include trailing space after command name (see Master Bot Pattern above)

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

## Common Development Tasks

### Adding Config-Driven Features

To add features that use configuration values (like `trusted_dirs`):

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

## Code Standards

### Implementation Rules

**Type Hints:**

- All functions must have type hints (enforced by mypy)
- Use `Optional[T]` for nullable types
- Use `List[T]`, `Dict[K, V]` from `typing` (Python 3.11)

**Async/Await:**

- All I/O operations are async (database, network, subprocess)
- Use `asyncio.create_subprocess_exec()` for shell commands
- Use `aiosqlite` for database operations
- Proper cleanup with `async with` or explicit `close()`

**Configuration:**

- Environment variables in `.env` for secrets (tokens, API keys, user IDs)
- YAML config (`config.yml`) for settings (computer name, paths, terminal sizes)
- Environment variable expansion in config: `${VAR}` syntax
- Config loaded once at daemon start (no hot reload in MVP)

**Error Handling:**

- Use `try/except` for recoverable errors (network, API failures)
- Log errors with `logger.error()` including context
- Return success boolean for operations that can fail
- Retry once for transient failures (Telegram API, Whisper)

### Style

As seen in [pyproject.toml](pyproject.toml):

**Black + isort:**

- Line length: 120 characters
- Black profile for isort
- Run `make format` before committing

**Pylint:**

- Disabled checks: `invalid-name`, `missing-docstring`, `too-few-public-methods`, `too-many-arguments`, `unused-argument`
- ENFORCED check: `import-outside-toplevel` (C0415) with `--fail-on` flag
- All other warnings should be addressed

**Naming Conventions:**

- Classes: `PascalCase` (e.g., `SessionManager`, `TelegramAdapter`)
- Functions/methods: `snake_case` (e.g., `create_session`, `send_keys`)
- Private methods: `_snake_case` (e.g., `_acquire_lock`, `_emit_message`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_SESSIONS`)
- Async functions: Same as sync, rely on `async def` keyword
- Module-level utility functions: `snake_case` without underscore prefix

**Docstrings:**

- Use triple quotes for all docstrings
- Function docstrings: brief description + Args + Returns
- Class docstrings: brief description of purpose
- Module docstrings: one-line overview of module purpose

## Installation Workflow

All installation is managed through make commands:

1. **`make install`** - Install Python dependencies (creates venv, installs packages)
2. **`make init`** - Run installation wizard that:
   - Detects OS (macOS/Linux)
   - Installs system dependencies (tmux, ffmpeg)
   - Creates `.env` and `config.yml` from templates
   - Prompts for Telegram bot token, user ID, supergroup ID
   - Generates system service file from template (launchd plist on macOS, systemd unit on Linux)
   - Starts system service with auto-restart enabled

**Unattended mode** (for CI/automation):

```bash
# In CI: environment variables already loaded by CI system
# Locally: source .env first if needed
make install && make init ARGS=-y
```

**Never** run `./install.sh` directly - always use `make init`.

## Multi-Computer Development Workflow

TeleClaude runs on multiple computers (development machine + remote RasPis). When making changes, you must update all instances.

### Standard Deployment Flow

1. **Make changes on development machine** (MozBook)
2. **Test locally**: `make restart && make status`
3. **Commit changes**: Use git commit (pre-commit hooks run automatically)
4. **Push to GitHub**: `git push`
5. **Deploy to ALL computers**: **ALWAYS use MCP tool first**

### Deploying to Remote Machines

**🚨 CRITICAL: ALWAYS use MCP tool for deployment!**

```python
# Primary method - NO ARGUMENTS, deploys to ALL computers automatically
teleclaude__deploy_to_all_computers()
# Automatically discovers all computers and deploys
# Returns: {"RasPi": {"status": "deployed", "pid": 12345}, ...}
```

**The MCP tool automatically:**
- Discovers ALL remote computers via Redis
- Sends deploy command to each computer (excluding self)
- Each computer: `git pull` → restart daemon
- Returns deployment status for each machine
- Handles timeouts and errors

**Manual deployment (ONLY if MCP server is down):**

Use SSH agent forwarding (`-A` flag) as fallback:

```bash
# RasPi (morriz@raspberrypi.local) - ONLY if MCP tool unavailable
ssh -A morriz@raspberrypi.local "cd /home/morriz/apps/TeleClaude && git checkout . && git pull && make restart"

# RasPi4 (morriz@raspi4.local)
ssh -A morriz@raspi4.local "cd /home/morriz/apps/TeleClaude && git checkout . && git pull && make restart"
```

**Why SSH agent forwarding (`-A`) is required:**
- Forwards your local SSH agent to the remote machine
- Remote git can use your local GitHub keys
- Enables git pull over SSH (git@github.com)
- Without it, git operations fail with "Permission denied (publickey)"

**Important**: Always use `git checkout .` before pull to discard any local changes from previous failed operations.

### Verification

After updating each machine, verify daemon is healthy:

```bash
# Check RasPi
ssh morriz@raspberrypi.local "cd /home/morriz/apps/TeleClaude && make status"

# Check RasPi4
ssh morriz@raspi4.local "cd /home/morriz/apps/TeleClaude && make status"
```

Expected output:
```
[INFO] Service: LOADED
[INFO] systemctl status: active
[INFO] Daemon process: RUNNING (PID: XXXXX, uptime: XX:XX)
[INFO] Daemon health: HEALTHY (health endpoint responding)
```

### Common Mistakes to Avoid

❌ **DON'T**: Manually SSH to each machine (use MCP tool!)
❌ **DON'T**: Use `make kill` (leaves orphaned MCP processes like socat)
❌ **DON'T**: Forget `-A` flag for manual SSH (causes git permission errors)
❌ **DON'T**: Change git remote from SSH to HTTPS (breaks key-based auth)
❌ **DON'T**: Skip verification after deployment

✅ **DO**: Use `teleclaude__deploy_to_all_computers()` MCP tool
✅ **DO**: Only use manual SSH if MCP server is down
✅ **DO**: Use `make restart` (clean daemon restart)
✅ **DO**: Verify daemon health after updates
✅ **DO**: Push to GitHub before deploying

## Technical Architecture

@docs/architecture.md

## Troubleshooting

@docs/troubleshooting.md
- ALWAYS USE `make restart` to RESTART the daemon!