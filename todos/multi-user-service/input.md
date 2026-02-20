# Multi-User Service User & System Installation

## Origin

Extracted from `multi-user-system-install` Phase 5. This phase makes TeleClaude run as a proper system service under a dedicated service user, with system-wide directory layout and service management via `launchd` (macOS) or `systemd` (Linux).

## Current State

Today, TeleClaude runs as the installing user:

- The daemon is a Python process started by `make start` or `bin/daemon-control.sh`
- macOS uses `launchd` via a user-level plist (already exists in `bin/daemon-control.sh`)
- Everything lives under the user's home directory or the project checkout
- The MCP socket is at `/tmp/teleclaude-api.sock` (world-accessible, no auth)
- Database is `teleclaude.db` in the project root
- Logs go to `~/Library/Logs/teleclaude/` (macOS) or stdout
- Shared docs are in the project tree and `~/.teleclaude/docs/`
- No concept of a service user or system directories

## What Needs to Change

### Service User

Create a dedicated `teleclaude` system user:

- macOS: `_teleclaude` (underscore prefix is the convention for system accounts, like `_postgres`)
- Linux: `teleclaude` (standard convention)
- No login shell, no home directory (uses system paths)
- Group: `teleclaude`
- Regular users who need MCP socket access are added to the `teleclaude` group

### System Directory Layout

```
/usr/local/share/teleclaude/     # Shared docs, global snippets, index
/var/lib/teleclaude/             # Database (SQLite fallback), runtime state
/var/log/teleclaude/             # Daemon logs
/var/run/teleclaude/             # PID file, MCP socket
  teleclaude.pid
  teleclaude.sock                # Was /tmp/teleclaude-api.sock
```

macOS variations:

- `/usr/local/share/teleclaude/` (same)
- `/usr/local/var/lib/teleclaude/` or `/var/db/teleclaude/` (macOS convention)
- `/usr/local/var/log/teleclaude/` or `~/Library/Logs/teleclaude/`
- `/usr/local/var/run/teleclaude/` or `/var/run/teleclaude/`

### Service Management

**`launchd` (macOS):**

- System-level LaunchDaemon plist at `/Library/LaunchDaemons/ai.instrukt.teleclaude.plist`
- Runs as `_teleclaude` user
- Auto-restart on failure
- Logs to system log location

**`systemd` (Linux):**

- Unit file at `/etc/systemd/system/teleclaude.service`
- Runs as `teleclaude` user
- `Restart=on-failure`, `WantedBy=multi-user.target`
- Journal-based logging

### Docker Compose

A turnkey deployment option: `docker-compose.system.yml` with:

- TeleClaude daemon container
- PostgreSQL container
- Shared volumes for config, data, logs
- Socket exposed to host for local MCP access

### Mode Detection

The daemon must detect at startup whether it's running in single-user or system-wide mode:

- System-wide: running as `teleclaude`/`_teleclaude` service user, system config exists
- Single-user: running as a regular user, project-root config only
- The mode determines which paths to use for everything (config, DB, logs, socket, docs)

## Open Questions

1. Socket location: `/var/run/teleclaude/teleclaude.sock` (conventional) vs `/tmp/teleclaude.sock` (current). The `/var/run/` path requires directory creation at boot or via the service unit.
2. macOS directory conventions: Apple has been locking down `/usr/local/` in recent versions. Should we use `~/Library/Application Support/TeleClaude/` for macOS single-user and `/Library/Application Support/TeleClaude/` for system-wide?
3. User group membership: should the installer automatically add the installing user to the `teleclaude` group?
4. PostgreSQL role creation: the installer should create the `teleclaude` database and role. How to handle auth (peer auth for local, password for Docker)?

## Dependencies

- Phase 0 (`multi-user-db-abstraction`): PostgreSQL backend support for the database parts
- Phase 4 (`multi-user-config`): Config separation into system/secrets/per-user (the installer needs to know where to put config files)
