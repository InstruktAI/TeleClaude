# Demo: discord-adapter-integrity

## Validation

```bash
# Lint clean
make lint
```

```bash
# Tests pass
make test
```

## Guided Presentation

### Step 1: Infrastructure hardening

1. Show `_ensure_discord_infrastructure` with the new `_validate_channel_id` helper.
2. Delete a Discord forum, restart the daemon, verify it re-creates automatically.

### Step 2: Per-computer project categories

1. Show the Discord guild sidebar — observe "Projects - MozBook" and "Projects - mozmini" as separate categories.
2. Show config.yml — each computer has its own category key (`categories.projects_mozbook`).
3. Start a session on each computer — observe the session thread appears in the correct computer-specific project forum.

### Step 3: Forum input routing

1. Send a message as admin in a project forum — verify the session creates with correct role ("member" or "admin", not "customer") and correct project path.
2. Verify the input text is delivered to the tmux session.
3. Send a message in the help desk forum — verify it still creates a customer session.
4. Check logs — verify `_handle_on_message` produces entry-level DEBUG logs.

### Step 4: Verify no regressions

1. Help desk customer flow unchanged — customer messages accepted in help desk, blocked elsewhere.
2. DM flow unchanged — identity resolution still works.
3. Existing session threads still route correctly.
