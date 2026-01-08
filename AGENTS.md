# AGENTS.md

This file provides guidance to agents when working with code in this repository.

> **For user-facing documentation, installation, and usage instructions, see [README.md](README.md)**

## 🚨 CRITICAL RULES (Never Break These)

### YOU ARE THE ONLY ONE MAKING CODE CHANGES

**CRITICAL SELF-AWARENESS: YOU ARE MAKING ALL CODE CHANGES. THERE IS NO "OLD CODE" vs "YOUR CHANGES".**

- When tests pass or fail, they are testing YOUR code changes
- Don't say "tests passed from old code before my changes" - that makes NO SENSE
- YOU are the developer. ALL changes are YOUR changes
- If tests don't catch a bug, the tests need improvement OR the bug only triggers at runtime
- Stop confusing yourself about whose code is whose - it's ALL YOUR RESPONSIBILITY

### THE DAEMON MUST NEVER BE DOWN

**USERS DEPEND ON THIS SERVICE 24/7. DOWNTIME IS NOT ACCEPTABLE.**

- Minimize downtime during development to absolute minimum
- After ANY change, IMMEDIATELY restart the daemon with `make restart`
- ALWAYS verify daemon is running before stepping away with `make status`
- If unsure about stability, test in a separate environment first
- The daemon provides critical infrastructure - treat restarts as production deployments

### Rule #1: SINGLE DATABASE ONLY

**THERE IS ONLY ONE DATABASE FILE: `teleclaude.db` IN PROJECT ROOT.**

- NEVER create additional database files
- NEVER copy or duplicate the database
- Database path is configured in `config.yml`: `${WORKING_DIR}/teleclaude.db`
- If you find multiple `.db` files, DELETE the extras immediately
- Any code that creates a new database file is a CRITICAL BUG

### Rule #2: MCP CONNECTION RESILIENCE

**The MCP wrapper handles all reconnection automatically - clients never need to restart.**

The resilient MCP wrapper (`bin/mcp-wrapper.py`) provides:

- **Zero-downtime restarts** - Cached handshake response while backend reconnects
- **Automatic reconnection** - Transparent backend connection recovery

See [docs/mcp-architecture.md](docs/mcp-architecture.md) for implementation details.

### Rule #3: AI-TO-AI COLLABORATION PROTOCOL

**Session lifecycle management tools:**

When orchestrating multiple AI workers, the master AI can manage session lifecycles:

- `teleclaude__get_session_data(computer, session_id)` - Get session data from a worker session.
- `teleclaude__stop_notifications(computer, session_id)` - Stop receiving events from a session without ending it. Use when you're done monitoring a completed worker.
- `teleclaude__end_session(computer, session_id)` - Gracefully terminate a session (kills tmux, marks closed, cleans up resources). Use when a worker has filled its context or needs replacement.

**Context exhaustion pattern:**

1. Monitor worker's context usage via `get_session_data`
2. When worker nears capacity, ask it to document findings
3. Call `end_session` to terminate gracefully
4. Start fresh session for continued work

## Essential Development Workflow

### Normal Development Cycle

The service is ALWAYS running (24/7 requirement). Never manually start the daemon with `python -m teleclaude.daemon` - always use `make` commands.

1. **Make code changes** as needed
2. **Restart daemon**: `make restart`
   - Runs `systemctl restart teleclaude` (proper systemd restart)
   - Daemon restarts in ~1-2 seconds
3. **Verify**: `make status`
4. **Monitor logs**: `. .venv/bin/activate && instrukt-ai-logs teleclaude --since 10m` (single log file; do not pass `log_filename` in code)

### Service Lifecycle Commands

```bash
make start                   # Enable and start service (after install or emergency stop)
make stop                    # Stop AND disable service (EMERGENCY ONLY - use when code goes haywire)
make restart                 # Restart daemon via systemctl (~1-2 sec)
make status                  # Check daemon status and uptime
```

**CRITICAL: Do NOT use `make stop` during normal development** - it disables the service completely. Only use in emergencies when code is broken and continuously crashing. For normal development, always use `make restart`.

### How Restarts Work

**Two different restart mechanisms:**

1. **Manual Restart** (`make restart`):

   - Runs `systemctl restart teleclaude`
   - Systemd sends SIGTERM → clean shutdown → starts fresh process
   - Used during development after code changes

2. **Deployment Restart** (automated):
   - Daemon receives `/deploy` command via Redis
   - Executes `git pull` + `make install`
   - Exits with code 42 → triggers `Restart=on-failure`
   - Systemd automatically restarts with new code
   - Enables zero-SSH multi-computer deployments

### Direct SSH Access to Remote Computers

**You can SSH directly into any online computer** for manual operations, debugging, or running commands.

**Get computer information:**

First, get the list of online computers with their connection details:

```python
teleclaude__list_computers()
```

This returns computer info including `user`, `host`, `name`, and `status`.

**SSH command format:**

```bash
ssh -A {user}@{host} '<commands>'
```

Replace `{user}` with the user field and `{host}` with the host field from the computer info.

**CRITICAL:**

- **Always use `-A` flag** for SSH agent forwarding (required for git operations)
- Use timeout of 10000ms for commands that might hang
- Run commands sequentially (one computer at a time)
- Quote commands properly when running multiple commands with `&&`

**Common SSH operations:**

```bash
# Check daemon status
ssh -A morriz@raspberrypi.local 'cd $HOME/apps/TeleClaude && make status'

# View recent logs
ssh -A morriz@raspberrypi.local 'cd $HOME/apps/TeleClaude && . .venv/bin/activate && instrukt-ai-logs teleclaude --since 10m'

# Restart daemon
ssh -A morriz@raspberrypi.local 'cd $HOME/apps/TeleClaude && make restart'

# Check running processes
ssh -A morriz@raspberrypi.local 'pgrep -f teleclaude.daemon'

# Pull latest code
ssh -A morriz@raspberrypi.local 'cd $HOME/apps/TeleClaude && git pull'
```

**When to use SSH vs MCP tools:**

- **Use MCP tools** (`teleclaude__start_session`, `teleclaude__send_message`) for AI-to-AI delegation
- **Use SSH** for direct system operations, debugging, manual intervention, or when MCP is unavailable

## Quick Command Reference

### Code Quality

```bash
make format                  # Format code (isort + black)
make lint                    # Run linting checks (pylint, mypy)
```

ALWAYS run `make lint` after changing code!

### Testing

```bash
make test-unit               # Run unit tests only
make test-e2e                # Run integration/e2e tests only
make test-all                # Run all tests
make test                    # Alias for test-all
```

ALWAYS run `make test` after changing code!

## Testing Requirements for Code Changes

**Before reporting completion of ANY code change:**

1. Add proper test case in `tests/unit/` or `tests/integration/`
2. Run `make test` to verify tests pass
3. Only report "Done" after automated tests pass
4. ❌ **NEVER rely on manual inspection** - write automated tests instead

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
  is_master: false  # These bots don't publish commands
```

**Trailing Space Pattern:**

BotCommand definitions **intentionally include trailing spaces**:

```python
commands = [
    BotCommand("new_session  ", "Create a new terminal session"),  # Note the trailing spaces
    BotCommand("list_sessions  ", "List all active sessions"),
]
```

**Why trailing spaces?**

- Without trailing space: Telegram appends `@botname` in autocomplete → `"/new_session@masterbot"`
- With trailing space: Commands are distributed to ALL bots → `"/new_session "` works for any bot
- Users can type commands without specifying which bot to use

**DO NOT remove trailing spaces from BotCommand definitions** - this is intentional, not a bug!

### UX Message Deletion System

**CRITICAL UX PATTERN for clean Telegram interface:**

The UI should never have message clutter. At any time, only ONE of each message type should be visible:

| Message Type                          | Tracking Mechanism                | Cleanup Trigger                |
| ------------------------------------- | --------------------------------- | ------------------------------ |
| User input messages                   | `pending_deletions` (db)          | Pre-handler on next user input |
| Feedback messages (summaries, errors) | `pending_feedback_deletions` (db) | `send_feedback(...)`           |
| Session download messages             | `pending_feedback_deletions` (db) | `send_feedback(...)`           |
| File artifacts (from agent)           | **NOT tracked**                   | **NEVER deleted**              |

**How it works:**

1. **Pre-handler** (`_pre_handle_user_input`): Runs BEFORE processing any user message - deletes old `pending_deletions` and idle notifications
2. **Post-handler** (`_call_post_handler`): Runs AFTER processing - adds current `message_id` to `pending_deletions`
3. **`send_feedback()`**: Deletes old feedback messages, sends new one, tracks it for future deletion

**Artifact vs download messages:**

- File artifact send messages must never be deleted.
- Session download messages (links shared with the user) are treated as feedback and should be cleaned up via `pending_feedback_deletions`.

**When adding new handlers:**

- If handler calls `handle_event()` with `message_id` in payload → automatic pre/post handling
- If handler bypasses `handle_event()` (e.g., shows help text directly):
  ```python
  await self._pre_handle_user_input(session)  # Delete old messages
  await db.add_pending_deletion(session.session_id, str(message.message_id))  # Track this one
  await self.send_feedback(session, "response", MessageMetadata())  # Use send_feedback, NOT reply_text
  ```

**NEVER use `reply_text()` for responses** - it bypasses tracking and messages accumulate forever!

## Code Standards

See global directives (automatically loaded for all projects):

- `~/.agents/docs/development/coding-directives.md`
- `~/.agents/docs/development/testing-directives.md`

## Technical Architecture

See [docs/architecture.md](docs/architecture.md)

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md)

- ALWAYS USE `make restart` to RESTART the daemon!

## Out-of-Band Telegram Alerts (When TeleClaude Is Down)

Sometimes you need to send a Telegram notification even when the TeleClaude daemon is down (no MCP socket, no adapters running). This repo includes **standalone** scripts for that purpose.

**Scripts (repo-local):**

- `bin/send_telegram.py` - Generic Telegram Bot API sender (uses `TELEGRAM_BOT_TOKEN` by default).
- `bin/notify_agents.py` - Opinionated alert sender:
  - Automatically creates (or reuses) a forum topic named **Agents** when possible
  - Uses exponential backoff to avoid spam (max 1/hour)
  - Persists state inside the repo at `logs/monitoring/`

**Usage:**

```bash
# Send a one-off message (direct chat id, or @username/display-name if a local Telegram session is configured)
./bin/send_telegram.py --chat-id -1001234567890 --text "Hello"

# Send an alert with backoff + auto-topic
./bin/notify_agents.py --prefix-host "Smoke test failed"

# Reset backoff after a successful run
./bin/notify_agents.py --reset
```

**MCP discovery helper:**

If an AI has access to the TeleClaude MCP server but lacks context, it can call `teleclaude__help` to discover these scripts and how to use them.

## Development Workflow: Rsync for Fast Iteration

**CRITICAL: Use rsync to sync changes during active development. Only commit when code is tested and working.**

### Why Rsync Over Git During Development

- **Faster iteration**: rsync syncs changes in <1 second vs git commit/push/pull cycle
- **Clean git history**: No WIP commits, no "fix typo", no broken intermediate states
- **Atomic commits**: Git commits represent complete, tested, working changes (Unix philosophy)
- **Production-ready**: Every commit can be deployed immediately

### Rsync Development Workflow

**CRITICAL: ALWAYS use `bin/rsync.sh` wrapper - NEVER raw rsync commands!**

The wrapper automatically uses `.rsyncignore` to protect `config.yml`, `.env`, databases, and other local files.

**Computer Registry:**

- All remote computers must be defined in `config.yml` under `remote_computers`
- Script ONLY accepts computer shorthand names from config (prevents mistakes)
- Each computer has: `user`, `host`, `ip`, `teleclaude_path`
- Example in `config.yml.sample`

**1. Make changes locally** (on development machine)

**2. Sync to remote computer** (use shorthand from config.yml)

```bash
# First see if remote has pending changes (might need stashing):
ssh -A user@hostname 'cd $HOME/apps/TeleClaude && git status'

# Sync to target computer (shorthand from config.yml)
bin/rsync.sh <computer-name>

# Restart daemon on remote
ssh -A user@hostname 'cd $HOME/apps/TeleClaude && make restart'

# Monitor remote logs
ssh -A user@hostname 'cd $HOME/apps/TeleClaude && . .venv/bin/activate && instrukt-ai-logs teleclaude -f'
```

**3. Iterate quickly** - repeat steps 1-2 until feature works

**4. Test thoroughly**:

```bash
make lint        # Verify code quality
```

**5. Only then commit** - when code is complete, tested, and working:

```bash
git add .
git commit -m "feat(component): add feature description"
git push
```

**NEVER use raw rsync commands** - they risk overwriting config.yml and .env!

---

**NEVER CHANGE CODE WITHOUT FULLY UNDERSTANDING WHAT IT DOES - IF UNSURE, INVESTIGATE DEEPER AND READ MORE FILES, ULTIMATELY ASKING THE USER FIRST!**
