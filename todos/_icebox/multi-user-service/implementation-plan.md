# Implementation Plan: Service User & System Installation (multi-user-service)

## Overview

Create the infrastructure for TeleClaude to run as a system-wide service. This involves: (1) a platform-aware path resolution module, (2) daemon mode detection logic, (3) an installer shell script, (4) service unit templates for launchd and systemd, and (5) a Docker Compose file for turnkey deployment.

The approach prioritizes the daemon's ability to resolve paths dynamically based on mode (single-user vs system-wide) as the foundation, then builds the installer and service units on top.

## Phase 1: Platform Path Resolution and Mode Detection

### Task 1.1: System directory layout constants

**File(s):** `teleclaude/config/system_paths.py` (new)

- [ ] Define dataclass `SystemLayout` with fields: `config_dir`, `secrets_path`, `data_dir`, `log_dir`, `run_dir`, `socket_path`, `shared_docs_dir`, `pid_file`
- [ ] Define platform-specific layouts:
  - Linux system-wide: `/etc/teleclaude/`, `/var/lib/teleclaude/`, `/var/log/teleclaude/`, `/var/run/teleclaude/`, `/usr/local/share/teleclaude/`
  - macOS system-wide: `/usr/local/etc/teleclaude/`, `/usr/local/var/lib/teleclaude/`, `/usr/local/var/log/teleclaude/`, `/usr/local/var/run/teleclaude/`, `/usr/local/share/teleclaude/`
  - Single-user (both platforms): project root for config, `~/.teleclaude/` for data, `/tmp/` for socket
- [ ] Expose `get_layout(mode: Literal["system", "single-user"]) -> SystemLayout` with platform auto-detection
- [ ] Use `sys.platform` for OS detection (`"darwin"` vs `"linux"`)

### Task 1.2: Daemon mode detection

**File(s):** `teleclaude/config/system_paths.py` (extend from 1.1)

- [ ] Add `detect_mode() -> Literal["system", "single-user"]` function that checks:
  1. Is the process running as the service user (`_teleclaude` / `teleclaude`)? -> system mode
  2. Does the system config path exist? -> system mode
  3. Is `TELECLAUDE_SYSTEM_MODE=1` set? -> system mode (explicit override)
  4. Otherwise -> single-user mode
- [ ] Log detected mode at daemon startup
- [ ] Export `current_layout()` convenience function that calls `detect_mode()` then `get_layout()`

### Task 1.3: Update MCP socket path to be dynamic

**File(s):** `teleclaude/constants.py`, `teleclaude/daemon.py`, `teleclaude/mcp_server.py`

- [ ] Replace hardcoded `MCP_SOCKET_PATH` constant with a function that returns the path based on current layout
- [ ] Update daemon startup to use the resolved socket path
- [ ] Update MCP server to use the resolved socket path
- [ ] Update any client code that references the socket path (search for `MCP_SOCKET_PATH` and `/tmp/teleclaude`)
- [ ] Ensure the socket directory exists before binding (create if in system mode)

---

## Phase 2: Installer Script

### Task 2.1: Installer script

**File(s):** `bin/install-system.sh` (new)

- [ ] Platform detection (macOS vs Linux) at the top of the script
- [ ] `--uninstall` flag support for removal
- [ ] `--dry-run` flag support for preview
- [ ] Service user creation:
  - macOS: `sysadminctl -addUser _teleclaude` or `dscl` commands (system account, no shell, no home)
  - Linux: `useradd --system --no-create-home --shell /usr/sbin/nologin teleclaude`
- [ ] Group creation and current user addition to the group
- [ ] Directory creation with correct ownership and permissions:
  - Config dir: root:teleclaude, 755
  - Secrets file: root:teleclaude, 640 (group-readable for the service)
  - Data dir: teleclaude:teleclaude, 750
  - Log dir: teleclaude:teleclaude, 750
  - Run dir: teleclaude:teleclaude, 755
  - Shared docs: teleclaude:teleclaude, 755
- [ ] Idempotency: check for existing user/dirs before creating
- [ ] Print summary of what was created

### Task 2.2: PostgreSQL database and role creation

**File(s):** `bin/install-system.sh` (extend from 2.1)

- [ ] Optional `--with-postgres` flag
- [ ] Check if PostgreSQL is installed and running
- [ ] Create `teleclaude` PostgreSQL role (if not exists)
- [ ] Create `teleclaude` database owned by the role (if not exists)
- [ ] Configure pg_hba.conf entry for peer auth (local socket) -- or document manual step
- [ ] Print connection string for config

### Task 2.3: Service unit installation

**File(s):** `bin/install-system.sh` (extend), `etc/teleclaude.service` (new), `etc/ai.instrukt.teleclaude.plist` (new)

- [ ] Copy service unit to the correct location:
  - macOS: `/Library/LaunchDaemons/ai.instrukt.teleclaude.plist`
  - Linux: `/etc/systemd/system/teleclaude.service`
- [ ] Enable but do not start the service (admin starts manually after config)
- [ ] Uninstall path: stop service, disable, remove unit file

---

## Phase 3: Service Unit Templates

### Task 3.1: systemd unit file

**File(s):** `etc/teleclaude.service` (new)

- [ ] `[Unit]` section: Description, After=network.target postgresql.service
- [ ] `[Service]` section:
  - `Type=notify` or `Type=simple`
  - `User=teleclaude`, `Group=teleclaude`
  - `ExecStart=` pointing to the Python entrypoint
  - `Restart=on-failure`, `RestartSec=5`
  - `WorkingDirectory=/usr/local/share/teleclaude`
  - `Environment=TELECLAUDE_SYSTEM_MODE=1`
  - `RuntimeDirectory=teleclaude` (auto-creates `/run/teleclaude/`)
  - `StateDirectory=teleclaude` (auto-creates `/var/lib/teleclaude/`)
  - `LogsDirectory=teleclaude` (auto-creates `/var/log/teleclaude/`)
- [ ] `[Install]` section: `WantedBy=multi-user.target`
- [ ] Security hardening: `ProtectSystem=strict`, `ProtectHome=read-only`, `NoNewPrivileges=true`

### Task 3.2: launchd plist

**File(s):** `etc/ai.instrukt.teleclaude.plist` (new)

- [ ] `Label`: `ai.instrukt.teleclaude`
- [ ] `UserName`: `_teleclaude`
- [ ] `GroupName`: `_teleclaude`
- [ ] `ProgramArguments`: path to Python entrypoint
- [ ] `KeepAlive`: true (auto-restart on failure)
- [ ] `RunAtLoad`: true
- [ ] `WorkingDirectory`: `/usr/local/share/teleclaude`
- [ ] `EnvironmentVariables`: `TELECLAUDE_SYSTEM_MODE=1`
- [ ] `StandardOutPath` and `StandardErrorPath`: log file paths

---

## Phase 4: Docker Compose

### Task 4.1: Docker Compose for system deployment

**File(s):** `docker-compose.system.yml` (new)

- [ ] PostgreSQL service:
  - Image: `postgres:16-alpine`
  - Volume for data persistence
  - Environment: `POSTGRES_DB=teleclaude`, `POSTGRES_USER=teleclaude`, `POSTGRES_PASSWORD` from env
  - Health check
- [ ] TeleClaude daemon service:
  - Build from project Dockerfile (or use published image)
  - Depends on PostgreSQL
  - Environment: database connection, API keys from `.env` file
  - Volume mounts: config, shared docs, socket
  - Socket exposed to host via bind mount
- [ ] Shared network between services
- [ ] `.env.example` file with required variables documented

---

## Phase 5: Validation and Tests

### Task 5.1: Tests for path resolution and mode detection

**File(s):** `tests/unit/test_system_paths.py` (new)

- [ ] Test `detect_mode()` returns `"single-user"` by default
- [ ] Test `detect_mode()` returns `"system"` when system config exists (mock file)
- [ ] Test `detect_mode()` returns `"system"` when `TELECLAUDE_SYSTEM_MODE=1` is set
- [ ] Test `get_layout("system")` returns correct Linux paths on Linux
- [ ] Test `get_layout("system")` returns correct macOS paths on macOS (mock `sys.platform`)
- [ ] Test `get_layout("single-user")` returns project-root-based paths
- [ ] Test dynamic socket path resolves correctly in both modes

### Task 5.2: Installer script tests

**File(s):** `tests/integration/test_installer.sh` (new) or manual test plan

- [ ] Test idempotency: running installer twice produces no errors
- [ ] Test `--dry-run`: no files or users created
- [ ] Test `--uninstall`: service unit removed, user optionally removed
- [ ] Test directory permissions are correct after install
- [ ] Document manual test plan for macOS and Linux (CI may not have root access)

### Task 5.3: Quality checks

- [ ] Run `make test` -- all existing tests pass
- [ ] Run `make lint` -- no new lint violations
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

## Risks and Mitigations

- **Risk**: macOS SIP restrictions on `/usr/local/`. **Mitigation**: Document Homebrew prefix requirement or use `/Library/Application Support/TeleClaude/` as fallback.
- **Risk**: launchd plist ownership and permission requirements are strict. **Mitigation**: Installer sets root:wheel ownership and 644 permissions on the plist.
- **Risk**: Docker Compose socket exposure complexity. **Mitigation**: Use a bind-mounted directory for the socket, document the pattern.
- **Risk**: PostgreSQL role/db creation requires superuser access. **Mitigation**: Installer runs as root (via sudo); PostgreSQL commands run as postgres user.

## Files Changed Summary

| File                                | Change                                              |
| ----------------------------------- | --------------------------------------------------- |
| `teleclaude/config/system_paths.py` | New: system layout, mode detection, path resolution |
| `teleclaude/constants.py`           | Modify: dynamic socket path                         |
| `teleclaude/daemon.py`              | Modify: use resolved paths at startup               |
| `teleclaude/mcp_server.py`          | Modify: use resolved socket path                    |
| `bin/install-system.sh`             | New: system installer script                        |
| `etc/teleclaude.service`            | New: systemd unit file                              |
| `etc/ai.instrukt.teleclaude.plist`  | New: launchd plist                                  |
| `docker-compose.system.yml`         | New: Docker Compose for system deployment           |
| `tests/unit/test_system_paths.py`   | New: path resolution and mode detection tests       |
