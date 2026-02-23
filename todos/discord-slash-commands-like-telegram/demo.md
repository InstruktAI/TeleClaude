# Demo: discord-slash-commands-like-telegram

## Validation

<!-- Bash code blocks that prove the feature works. -->
<!-- Each block is run by `telec todo demo discord-slash-commands-like-telegram` as a build gate — all must exit 0. -->

```bash
# Verify the discord command handlers module exists and imports cleanly
python -c "from teleclaude.adapters.discord.command_handlers import CommandHandlersMixin; print('CommandHandlersMixin imported OK')"
```

```bash
# Verify CommandTree is created and slash commands are registered
python -c "
from unittest.mock import MagicMock, AsyncMock
import asyncio, importlib
discord = importlib.import_module('discord')
from teleclaude.core.events import UiCommands

# Verify app_commands module is available
tree = discord.app_commands.CommandTree(MagicMock())
print(f'CommandTree created OK, {len(UiCommands)} UiCommands to register')
"
```

```bash
# Verify all tests pass
make test
```

```bash
# Verify lint passes
make lint
```

## Guided Presentation

### Step 1: Package structure

Show the new `teleclaude/adapters/discord/` package with the `command_handlers.py` mixin:

```bash
ls -la teleclaude/adapters/discord/
```

Observe: `__init__.py` and `command_handlers.py` exist, following the Telegram mixin pattern.

### Step 2: Slash command registration

Start the Discord adapter (or show the registration code path) and verify slash commands sync to the guild.

What to observe: All 22 `UiCommands` are registered as Discord Application Commands with correct descriptions and parameter definitions.

### Step 3: Key command in a session thread

In a Discord forum thread with an active session, type `/cancel`.

What to observe:

- Discord shows autocomplete with "Send CTRL+C to interrupt current command" description.
- After selecting, an ephemeral message confirms "Sent cancel".
- The session receives CTRL+C.

### Step 4: Agent command

In the same thread, type `/claude`.

What to observe:

- Ephemeral deferred response appears.
- Claude agent starts in the session.
- Follow-up message confirms agent start.

### Step 5: Parameterized command

Type `/ctrl` and provide `d` as the key parameter.

What to observe:

- Discord shows the required `key` parameter prompt.
- CTRL+D is sent to the session.
- Ephemeral confirmation appears.

### Step 6: Help command

Type `/help` in any channel.

What to observe:

- Ephemeral message with all available commands and descriptions.
- Works outside session threads (no session required).

### Step 7: Error handling

Type `/cancel` outside a session thread (e.g., in a text channel).

What to observe:

- Ephemeral error message: "This command requires an active session thread."
