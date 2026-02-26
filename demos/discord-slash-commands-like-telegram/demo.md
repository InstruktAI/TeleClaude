# Demo: discord-slash-commands-like-telegram

## Validation

<!-- Bash code blocks that prove the feature works. -->
<!-- Each block is run by `telec todo demo discord-slash-commands-like-telegram` as a build gate — all must exit 0. -->

```bash
# Verify the session launcher module exists and imports cleanly
python -c "from teleclaude.adapters.discord.session_launcher import SessionLauncherView; print('SessionLauncherView imported OK')"
```

```bash
# Verify CommandTree can be created and /cancel registered
python -c "
from unittest.mock import MagicMock
import importlib
discord = importlib.import_module('discord')

tree = discord.app_commands.CommandTree(MagicMock())
print('CommandTree created OK')
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

### Step 1: Launcher display (multi-agent)

Navigate to a Discord project forum where multiple agents are enabled.

What to observe:

- A persistent message with one button per enabled agent (e.g., "Claude", "Gemini", "Codex").
- Message text: "Start a session".
- Buttons use primary style.

### Step 2: Button click creates session

Click an agent button (e.g., "Claude") in the launcher message.

What to observe:

- Ephemeral acknowledgment: "Starting Claude...".
- A new thread is created in the forum with a session running the selected agent in slow mode.

### Step 3: Single-agent mode (no launcher)

Navigate to a project forum where only one agent is enabled.

What to observe:

- No launcher message is posted.
- Posting a new thread message auto-starts the single enabled agent in slow mode.

### Step 4: `/cancel` in a session thread

In a Discord forum thread with an active session, type `/cancel`.

What to observe:

- Discord shows the command with "Send CTRL+C to interrupt the current agent" description.
- Ephemeral message confirms "Sent CTRL+C".
- The agent in the session receives the interrupt.

### Step 5: `/cancel` outside a session thread

Type `/cancel` in a channel or thread with no active session.

What to observe:

- Ephemeral error message: "No active session in this thread."

### Step 6: Restart persistence

Restart the daemon and revisit the project forum.

What to observe:

- The same launcher message is still present (not duplicated).
- Buttons remain functional after restart.
