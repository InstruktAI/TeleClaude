# Demo: help-desk-startup-command-ordering

## Validation

```bash
uv run pytest tests/unit/test_command_handlers.py -k "process_message and initializing"
uv run pytest tests/unit/test_daemon.py -k "bootstrap and auto_command"
uv run pytest tests/unit/test_discord_adapter.py -k "creates_session_and_dispatches_process_message"
```

## Guided Presentation

### Step 1: Create a fresh help-desk session via first inbound message

Send a new customer message in the help-desk channel/thread and capture the
created session id.

### Step 2: Verify startup ordering in logs

```bash
instrukt-ai-logs teleclaude --since 20m --grep "session_bootstrap|agent_start|Message for session|initializing"
```

Expected:

1. Session remains `initializing` until bootstrap auto-command dispatch attempt completes.
2. If first message arrives early, log shows gated wait then release before tmux injection.

### Step 3: Confirm pane command integrity

Open the target tmux pane and inspect the first startup line plus first customer
message injection.

Expected:

1. Startup command line contains only startup command arguments.
2. First customer message appears as a separate input action.
3. Agent responds to first message normally.

### Step 4: Timeout branch sanity check (test harness)

Force startup readiness timeout in unit tests.

Expected:

1. User-visible feedback path is emitted.
2. No tmux send occurs for timed-out message.
