# Contributing to TeleClaude

This document provides guidance for developers working on TeleClaude codebase.

## Table of Contents

1. [Command Implementation Patterns](#command-implementation-patterns)
2. [Common Development Tasks](#common-development-tasks)
3. [Code Standards](#code-standards)

---

## Command Implementation Patterns

### Clean UX Rule for Telegram Adapter

**CRITICAL**: Telegram adapter (`has_ui=True`) follows strict message management rules for clean UX:

**Output Messages (from tmux commands):**

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
   ⚠️ **IMPORTANT**: Include trailing space after command name (see Master Bot Pattern in CLAUDE.md)

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

4. **Dispatch command directly** from the adapter handler:
   - Build the typed command object (see `teleclaude/types/commands.py`)
   - Call the explicit command service method (see `teleclaude/core/command_service.py`)
   - Use `_dispatch_command(...)` to apply pre/post hooks and broadcast

5. **Add to UiCommands** in `teleclaude/core/events.py`:

   ```python
   UiCommands = {
       # ... existing commands
       "command_name": "Description of what this command does",
   }
   ```

   ⚠️ **NOTE**: Help text is dynamically generated from `UiCommands` - no need to edit `_handle_help()`!

### Using Inline Keyboards for User Selections

Pattern for creating clickable button menus (like project selection):

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
cmd = f"some_command {shlex.quote(user_input)}"

# WRONG (vulnerable to spaces, injection):
cmd = f"some_command {user_input}"
```

This handles:

- Paths with spaces
- Special shell characters (`$`, `;`, `|`, etc.)
- Quote characters

---

## Common Development Tasks

### Adding Config-Driven Features

To add features that use configuration values (like `trusted_dirs`):

1. **Add to `config.sample.yml`** with comments and examples
2. **Pass from daemon to adapter** in adapter config:
   ```python
   adapter_config = {
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
3. Implement all abstract methods:
   - `start()` / `stop()` - Lifecycle
   - `send_message()` / `edit_message()` / `delete_message()` - Messaging
   - `create_channel()` / `update_channel_title()` / `delete_channel()` - Channel management
4. Set `has_ui` flag appropriately:
   - `True` for UI platforms (Telegram, Slack, etc.)
   - `False` for pure transport adapters (Redis, Postgres, etc.)
5. Add adapter initialization in `daemon.py`
6. Update config schema for platform-specific settings

### Modifying Database Schema

1. Update `teleclaude/core/schema.sql`
2. Add migration logic in `SessionManager.initialize()`:

   ```python
   # Check if column exists
   cursor = await self.db.execute("PRAGMA table_info(sessions)")
   columns = {row[1] for row in await cursor.fetchall()}

   if "new_column" not in columns:
       await self.db.execute("ALTER TABLE sessions ADD COLUMN new_column TEXT")
       await self.db.commit()
   ```

3. Test with existing database (daemon should auto-migrate on startup)
4. Update `models.py` if data classes change

### Adding New Configuration Options

1. Add to `config.sample.yml` with comments and example values:
   ```yaml
   new_feature:
     enabled: true
     option: "value" # Description of what this does
   ```
2. Document in `docs/architecture.md` or relevant doc
3. Access via `self.config[key]` in daemon
4. Add validation in `daemon.py` `__init__` if required field:
   ```python
   if not self.config.get("new_feature"):
       raise ValueError("new_feature configuration is required")
   ```

---

## Code Standards

See global directives (automatically loaded for all projects):

- `~/.claude/docs/development/coding-directives.md`
- `~/.claude/docs/development/testing-directives.md`

### Quick Reference

- Run `make format` before committing (isort + black)
- Run `make lint` to check for issues (pylint + mypy)
- Run `make test` to verify tests pass

---

## Development Workflow

### Normal Development Cycle

1. **Make code changes**
2. **Format code**: `make format`
3. **Run linting**: `make lint`
4. **Run tests**: `make test`
5. **Restart daemon**: `make restart`
6. **Verify**: `make status`
7. **Monitor logs**: `instrukt-ai-logs teleclaude --since 10m`

**Never stop the service to check logs** - use `instrukt-ai-logs` instead.

### Service Lifecycle Commands

### Quick Reference

```bash
# Code quality
make format                  # Format code (isort + black)
make lint                    # Run linting checks (pylint, mypy)

# Testing
make test-unit               # Run unit tests only
make test-e2e                # Run integration/e2e tests only
make test                    # Run all tests

# Service management
make restart                 # Restart daemon
make status                  # Check daemon status
```

---

## Architecture References

For detailed architecture documentation:

- `docs/architecture.md` - Technical architecture reference
- `docs/protocol-architecture.md` - Cross-computer orchestration patterns
- `docs/troubleshooting.md` - Debugging guide
- `CLAUDE.md` - Critical rules and coding directives

---

**When in doubt, follow the patterns in existing code and ask for review!**
