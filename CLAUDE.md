# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **For user-facing documentation, installation, and usage instructions, see [README.md](README.md)**

## 🚨 CRITICAL RULES (Never Break These)

### YOU ARE THE ONLY ONE MAKING CODE CHANGES

**CRITICAL SELF-AWARENESS: YOU (CLAUDE) ARE MAKING ALL CODE CHANGES. THERE IS NO "OLD CODE" vs "YOUR CHANGES".**

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

### Rule #2: MCP CONNECTION POLICY

**CRITICAL**: MCP connection behavior depends on terminal context.

**In tmux sessions:**

- MCP connection automatically reconnects after `make restart`
- You can continue testing MCP tools immediately

**In normal terminal sessions:**

- MCP connection is PERMANENTLY LOST after `make restart`
- Claude Code maintains old socket connection that cannot reconnect
- You CANNOT do anything to fix this
- You MUST ask the user to restart the Claude Code session
- If MCP tools return empty/stale results after restart, ask user: "The MCP connection was lost during daemon restart. Please restart this Claude Code session to reconnect."

### Rule #3: AI-TO-AI COLLABORATION PROTOCOL

**CRITICAL**: Messages from other AIs are prefixed with sender identification.

**Message Format:**

```
AI[computer:session_id] | message content here
```

- `computer` - Either `"local"` (same computer) or a remote computer name
- `session_id` - The sender's session UUID (for reference)
- `|` - Separator between header and message
- `message` - The actual request/content

**When you receive a message starting with `AI[...]`:**

1. **Recognize it's from another AI**, not a human
2. **Complete the requested task**
3. **Just finish your work** - the caller is notified automatically when you stop

**Automatic completion notification:**

The calling AI gets notified automatically when your session stops (via PUB-SUB listeners).
You do NOT need to explicitly call `send_message` to report completion.

**Health checks for long-running work:**

If you're working for more than 10 minutes, you may receive a health check message asking for status.
In that case, use `teleclaude__send_message` to report progress, then continue your work.

**Why this matters:**

- The calling AI is automatically notified when you finish
- No manual callback needed - just complete your task
- For long work, periodic status updates help the caller know you're still working

## Essential Development Workflow

### Normal Development Cycle

The service is ALWAYS running (24/7 requirement). Never manually start the daemon with `python -m teleclaude.daemon` - always use `make` commands.

1. **Make code changes** as needed
2. **Restart daemon**: `make restart`
   - Runs `systemctl restart teleclaude` (proper systemd restart)
   - Daemon restarts in ~1-2 seconds
3. **Verify**: `make status`
4. **Monitor logs**: `tail -f /var/log/teleclaude.log`

**Never stop the service to check logs** - use `tail -f` instead.

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
ssh -A morriz@raspberrypi.local 'cd /home/morriz/apps/TeleClaude && make status'

# View recent logs
ssh -A morriz@raspberrypi.local 'tail -50 /var/log/teleclaude.log'

# Restart daemon
ssh -A morriz@raspberrypi.local 'cd /home/morriz/apps/TeleClaude && make restart'

# Check running processes
ssh -A morriz@raspberrypi.local 'pgrep -f teleclaude.daemon'

# Pull latest code
ssh -A morriz@raspberrypi.local 'cd /home/morriz/apps/TeleClaude && git pull'
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
  is_master: false  # These bots clear their command lists
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
- Prevents duplicate command entries when multiple bots are in the same group
- Users can type commands without specifying which bot to use

**DO NOT remove trailing spaces from BotCommand definitions** - this is intentional, not a bug!

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

## Technical Architecture

docs/architecture.md

## Troubleshooting

docs/troubleshooting.md

- ALWAYS USE `make restart` to RESTART the daemon!

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

**2. Sync to remote computer** (use shorthand from config.yml):

```bash
# Sync to target computer (shorthand from config.yml)
bin/rsync.sh <computer-name>

# Restart daemon on remote
ssh -A user@hostname 'cd $HOME/apps/TeleClaude && make restart'

# Monitor remote logs
ssh -A user@hostname 'tail -f /var/log/teleclaude.log'
```

**3. Iterate quickly** - repeat steps 1-2 until feature works

**4. Test thoroughly**:

```bash
make test        # Run all tests
make lint        # Verify code quality
```

**5. Only then commit** - when code is complete, tested, and working:

```bash
git add .
git commit -m "feat(component): add feature description"
git push
```

**NEVER use raw rsync commands** - they risk overwriting config.yml and .env!

### When to Commit

✅ **DO commit when:**

- All tests pass (`make test`)
- All lint checks pass (`make lint`)
- Feature is complete and working
- Code has been tested on target environments
- Change represents one atomic, logical unit

❌ **DO NOT commit:**

- Work-in-progress code
- Broken or untested code
- Debug statements or temporary changes
- "Just to save my work" (use git stash or rsync instead)

### Git Philosophy

**Unix thinking: Each commit does one thing completely and well.**

- Commits are atomic units of working software
- Git is version control, not a backup tool
- History should tell a story of deliberate, complete changes
- Every commit in main branch should be deployable

---

**NEVER CHANGE CODE WITHOUT FULLY UNDERSTANDING WHAT IT DOES - IF UNSURE, INVESTIGATE DEEPER AND READ MORE FILES, ULTIMATELY ASKING THE USER FIRST!**
