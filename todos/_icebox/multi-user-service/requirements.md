# Requirements: Service User & System Installation (multi-user-service)

## Goal

Make TeleClaude run as a proper system service under a dedicated service user with standard system directories, managed by `launchd` (macOS) or `systemd` (Linux). Provide an installer script and Docker Compose option for turnkey deployment.

## Problem Statement

Today, the daemon runs as the installing user with all data in the project checkout or home directory. This prevents multi-user deployments: the MCP socket has no access control, the database is owned by one user, and there's no system-level service management. A shared machine needs the daemon running as a system service with proper directory ownership and access controls.

## In Scope

1. **Service user creation**: A dedicated `teleclaude` (Linux) / `_teleclaude` (macOS) system user and group.
2. **System directory layout**: Standard paths for shared docs, database, logs, runtime state, and MCP socket.
3. **Platform path constants**: A module that resolves paths based on platform and mode (single-user vs system-wide).
4. **Service unit files**: `launchd` plist (macOS) and `systemd` unit (Linux) for the daemon.
5. **Installer script**: `bin/install-system.sh` that creates user, directories, permissions, installs service unit, and optionally creates PostgreSQL database+role.
6. **Docker Compose**: `docker-compose.system.yml` with TeleClaude + PostgreSQL for turnkey multi-user deployment.
7. **Daemon mode detection**: At startup, detect single-user vs system-wide mode and configure all paths accordingly.
8. **Socket relocation**: MCP socket moves from `/tmp/teleclaude-api.sock` to the system run directory in system-wide mode.
9. **File permissions**: Shared resources world-readable, database owned by service user, secrets root-only, socket accessible to group members.

## Out of Scope

- Database backend abstraction (that's `multi-user-db-abstraction`).
- Config file splitting logic (that's `multi-user-config`).
- Data migration from SQLite to PostgreSQL (that's `multi-user-migration`).
- OS user identity resolution and socket auth (that's `multi-user-identity`).
- TUI changes for multi-user views.

## Success Criteria

- [ ] `bin/install-system.sh` creates the service user, all system directories, sets correct permissions, and installs the service unit -- idempotently (safe to run multiple times).
- [ ] The `teleclaude` service user exists with no login shell and no home directory.
- [ ] Service starts via `launchctl load` (macOS) or `systemctl start teleclaude` (Linux) and the daemon is reachable on the system socket.
- [ ] Service auto-restarts on failure.
- [ ] In system-wide mode, the daemon reads config from `/etc/teleclaude/` (Linux) or `/usr/local/etc/teleclaude/` (macOS).
- [ ] In system-wide mode, the MCP socket is at the system run directory, accessible to `teleclaude` group members.
- [ ] In single-user mode, all paths resolve to project root / home directory as today. Zero behavioral change.
- [ ] Docker Compose brings up TeleClaude + PostgreSQL with a single `docker compose up`.
- [ ] Uninstall path: `bin/install-system.sh --uninstall` removes the service unit and optionally the service user (but preserves data directories).
- [ ] All existing tests pass without modification.

## Constraints

- macOS service user names must start with underscore (`_teleclaude`).
- `launchd` plists must be valid XML property lists.
- `systemd` units must follow freedesktop conventions.
- The installer must not require Python -- it's a shell script that runs before TeleClaude is installed.
- The installer must detect the platform (macOS vs Linux) and run the appropriate commands.
- Docker Compose must work with both Docker Compose v1 (`docker-compose`) and v2 (`docker compose`).
- The `MCP_SOCKET_PATH` constant in `teleclaude/constants.py` must be updated to support dynamic path resolution.

## Risks

- **macOS directory restrictions**: Recent macOS versions restrict writing to `/usr/local/` via SIP. Mitigation: use Homebrew-compatible paths or fall back to `/Library/Application Support/TeleClaude/` if needed.
- **launchd plist complexity**: macOS `launchd` has specific requirements for daemon plists (must be owned by root, must have specific keys). Mitigation: research Apple's documentation and test on a real macOS system.
- **Socket permissions**: Group-readable socket requires correct group membership. Mitigation: installer adds the installing user to the `teleclaude` group.
- **PostgreSQL role creation**: The installer creates the DB role, but PostgreSQL auth configuration varies. Mitigation: support both peer auth (default for local) and password auth (Docker). Document common setups.
- **Cross-platform testing**: Hard to test macOS-specific code in Linux CI and vice versa. Mitigation: mock platform detection in tests; do manual testing on both platforms.

## Design Decisions

1. **Shell script installer, not Python**: The installer runs before TeleClaude's Python environment exists. It creates the user, directories, and service unit. Python-level setup (database creation, config splitting) is handled by separate tools that run after installation.
2. **Idempotent installer**: Running the installer multiple times is safe. It checks for existing users, directories, and units before creating them.
3. **Detection-based mode**: The daemon detects system-wide mode by checking if it's running as the service user or if the system config exists. No explicit mode flag.
4. **Group-based socket access**: Users in the `teleclaude` group can access the MCP socket. This is simpler than ACLs and well-understood.
5. **Separate Docker Compose file**: `docker-compose.system.yml` is distinct from any development compose file. It's the production multi-user deployment path.

## Dependencies

- `multi-user-db-abstraction` (Phase 0): PostgreSQL support for the database. The installer creates the PostgreSQL database and role, but the daemon's ability to use it depends on Phase 0.
- `multi-user-config` (Phase 4): Config separation. The installer creates the config directory structure, but the daemon's ability to load from it depends on Phase 4.
