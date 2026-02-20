# DOR Report: multi-user-service

## Draft Assessment (not a formal gate verdict)

### Gate 1: Intent & Success -- PASS

The goal is clear: TeleClaude runs as a system service under a dedicated user with standard system directories. Success criteria are concrete (installer creates user/dirs, service starts, socket is reachable).

### Gate 2: Scope & Size -- PASS (borderline)

This is a large phase with 12+ tasks spanning Python code, shell scripts, service units, and Docker Compose. However, the tasks are well-defined and sequential. The Python changes (path resolution, mode detection) are moderate. The installer script is the bulk of the work. Fits a single focused session.

### Gate 3: Verification -- PASS

- Path resolution: unit testable with mocked platform
- Mode detection: unit testable with mocked files and env vars
- Installer: testable via dry-run mode and manual verification
- Service units: testable by loading/starting on target platforms
- Docker Compose: testable by bringing up the stack

### Gate 4: Approach Known -- NEEDS WORK

The general approach is well-understood (service users, systemd units, launchd plists are standard patterns), but specific details need research:

- **launchd plist requirements**: macOS has specific ownership, permission, and key requirements for LaunchDaemons. The exact `ProgramArguments` path (pointing to a uv-managed Python) needs to be determined.
- **systemd unit best practices**: Security hardening directives (`ProtectSystem`, `NoNewPrivileges`, etc.) need verification against the daemon's actual requirements (e.g., does it need write access to `/usr/local/share/`?).
- **macOS system account creation**: The `sysadminctl` vs `dscl` approach for creating system accounts on modern macOS needs verification.
- **Socket directory lifecycle**: `RuntimeDirectory=` in systemd auto-creates `/run/teleclaude/` with correct ownership. macOS has no equivalent -- the installer must handle this.

### Gate 5: Research Complete -- NEEDS WORK

Three research items remain:

1. **launchd plist conventions for Python services**: How to point `ProgramArguments` at a uv-managed Python environment. What `EnvironmentVariables` are needed for PATH.
2. **systemd unit security hardening**: Which directives are compatible with the daemon's actual filesystem access patterns.
3. **macOS system account creation**: Modern (Ventura+) approach for creating system service accounts without `sysadminctl` GUI prompts.

### Gate 6: Dependencies & Preconditions -- NEEDS WORK

- **Depends on Phase 0 (`multi-user-db-abstraction`)**: The installer creates a PostgreSQL database and role, which the daemon needs Phase 0 to actually use.
- **Depends on Phase 4 (`multi-user-config`)**: The installer creates the config directory structure, but the daemon needs Phase 4 to load from it.
- **Partial independence**: The path resolution module, mode detection, and installer infrastructure can be built independently. The daemon's ability to actually use these paths for config loading and database depends on the other phases.

### Gate 7: Integration Safety -- PASS

- Single-user mode is the default. System-wide mode activates only when explicitly installed.
- The dynamic socket path falls back to `/tmp/teleclaude-api.sock` in single-user mode.
- The installer is a separate script -- it doesn't modify existing code behavior.
- Service units are installed but not started by default.

### Gate 8: Tooling Impact -- PARTIAL

The installer is new tooling. The service units are new operational artifacts. These don't affect the development workflow but do affect deployment. Documentation for the new installation path will be needed (deferred to `multi-user-doc-updates` or similar).

## Assumptions

1. `uv` (or pip) provides a stable Python entrypoint path that can be referenced from service units.
2. macOS does not prevent the creation of system service accounts via command-line tools (no SIP interference for user creation).
3. The daemon can write to system log directories when running as the service user.
4. Docker Compose bind-mounted Unix sockets work correctly for MCP client access from the host.
5. PostgreSQL peer authentication works for the `teleclaude` system user connecting locally.

## Open Questions

1. **Socket location**: `/var/run/teleclaude/teleclaude.sock` is conventional but requires directory creation. systemd `RuntimeDirectory=` handles this on Linux. macOS needs the installer or a LaunchDaemon-managed directory. Decision needed before build.
2. **Python entrypoint path**: The service unit needs an absolute path to the Python binary. With `uv`, this is typically `$PROJECT_ROOT/.venv/bin/python -m teleclaude.daemon`. Need to decide if system-wide mode uses a system-level venv or the project checkout's venv.
3. **macOS paths**: Should macOS system-wide use `/Library/Application Support/TeleClaude/` (Apple convention) or `/usr/local/var/` (Homebrew convention)?

## Score: 5/10

**Status: needs_work**

The scope is well-defined but research gaps in launchd/systemd specifics, macOS system account creation, and the Python entrypoint path are blocking. The dependency on Phases 0 and 4 means the daemon can't fully use the system layout until those phases deliver.

**Blockers:**

- Depends on Phases 0 (`multi-user-db-abstraction`) and 4 (`multi-user-config`)
- launchd/systemd research needed for service unit specifics
- Socket location decision pending (impacts installer, service units, and daemon code)
