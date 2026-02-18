# Implementation Plan: Multi-User System-Wide Installation

## Overview

This is a large architectural project that **must be split into dependent sub-todos** before any build work begins. A single AI session cannot implement this safely. The plan below defines the phased breakdown; each phase should become its own todo with proper DOR gating.

The approach follows the PostgreSQL/Docker analogy from the input: system daemon, per-user authentication via socket credentials, role-based access to shared state.

## Recommended Todo Breakdown

### Phase 1: OS User Identity Resolution (sub-todo: `multi-user-identity`)

**Goal**: Daemon can resolve a connecting Unix socket client's OS user to a TeleClaude person and role.

**File(s):** `teleclaude/config/schema.py`, `teleclaude/core/socket_auth.py` (new), `teleclaude/entrypoints/mcp_wrapper.py`, `teleclaude/mcp/server.py`

- [ ] Add `os_username: Optional[str]` field to `PersonEntry` config schema
- [ ] Create platform abstraction module for Unix socket peer credentials:
  - `SO_PEERCRED` (Linux) and `LOCAL_PEERCRED` (macOS)
  - Given a connected socket, return the peer's UID
  - Map UID → OS username → person lookup in config
  - Unknown UID → `public` role (least privilege)
- [ ] Integrate peer credential resolution into MCP socket accept path
- [ ] Inject resolved person identity (name + role) into command context alongside `caller_session_id`
- [ ] Tests: unit tests for credential extraction, person resolution, unknown-UID fallback
- [ ] Research: `SO_PEERCRED`/`LOCAL_PEERCRED` Python API (socket module support)

**Dependencies**: None. This is the foundation.

---

### Phase 2: Session Ownership & Visibility (sub-todo: `multi-user-sessions`)

**Goal**: Every session records its owner. Visibility is role-scoped.

**File(s):** `teleclaude/core/schema.sql`, `teleclaude/core/migrations/` (new), `teleclaude/core/db.py`, `teleclaude/commands/`, `teleclaude/api/`, `teleclaude/cli/tui/`

- [ ] Add `owner_person` TEXT and `owner_uid` INTEGER columns to `sessions` table
- [ ] Populate ownership on session creation from resolved identity
- [ ] Add session query filtering: member sees own sessions, admin sees all
- [ ] API server: filter session list by caller identity
- [ ] MCP tools: scope `list_sessions` results by caller role
- [ ] TUI: show owner badge on sessions belonging to other users (admin view)
- [ ] Session start notice: "Sessions on this system are subject to admin audit"
- [ ] Tests: ownership assignment, visibility filtering, role boundary checks

**Dependencies**: Phase 1 (identity resolution must exist first).

---

### Phase 3: Admin Observability & Audit (sub-todo: `multi-user-admin-audit`)

**Goal**: Admin can access session transcripts explicitly, and that access is logged.

**File(s):** `teleclaude/core/schema.sql` (audit table), `teleclaude/api/`, `teleclaude/commands/`, `teleclaude/cli/tui/`

- [ ] Create `audit_log` table (who, what, when, target_session_id)
- [ ] Admin transcript access endpoint: explicit action, not default
- [ ] Log every admin transcript access to audit table
- [ ] TUI admin view: metadata always visible, transcript requires explicit action
- [ ] API: transcript endpoint checks caller role + logs access
- [ ] Tests: audit logging, role-gated transcript access, log integrity

**Dependencies**: Phase 2 (session ownership must exist).

---

### Phase 4: Config Separation (sub-todo: `multi-user-config`)

**Goal**: Split config into system, secrets, and per-user layers.

**File(s):** `teleclaude/config/`, `teleclaude/daemon.py`, per-user config loading

- [ ] Define config file hierarchy:
  - `/etc/teleclaude/config.yml` or `/usr/local/etc/teleclaude/config.yml` — system config (people, projects, adapters)
  - `/etc/teleclaude/secrets.yml` — API keys, tokens (600 permissions, root-owned)
  - `~/.teleclaude/config.yml` — personal preferences (thinking mode, default model)
- [ ] Update config loading to merge layers: system → secrets → per-user
- [ ] Per-user config cannot override system-level settings (people, roles, projects)
- [ ] Config validation rejects secrets in per-user files
- [ ] Migration tool: split existing single `config.yml` into the three layers
- [ ] Tests: config merging, layer precedence, secrets isolation

**Dependencies**: Phase 1 (identity resolution informs which per-user config to load).

---

### Phase 5: Service User & System Installation (sub-todo: `multi-user-service`)

**Goal**: Daemon runs under a dedicated `teleclaude` service user with proper service management.

**File(s):** `bin/install-system.sh` (new), `etc/` (new — service unit files), `teleclaude/daemon.py`

- [ ] Define system directory layout:
  - `/usr/local/share/teleclaude/` — shared docs, global snippets, index
  - `/var/lib/teleclaude/` — database, runtime state
  - `/var/log/teleclaude/` — daemon logs
  - `/tmp/teleclaude.sock` or `/var/run/teleclaude/teleclaude.sock` — MCP socket
- [ ] Create `teleclaude` service user (like `_postgres`, `_mysql`)
- [ ] Write `launchd` plist (macOS) and `systemd` unit (Linux)
- [ ] Installer script: create user, directories, set permissions, install unit
- [ ] Daemon startup: detect system-wide vs single-user mode and load paths accordingly
- [ ] File permissions: shared resources world-readable, secrets root-only, DB service-user-owned
- [ ] Tests: installation script idempotency, permission checks, service lifecycle

**Dependencies**: Phase 4 (config separation must exist so the service user knows where to find config).

---

### Phase 6: Migration Tooling (sub-todo: `multi-user-migration`)

**Goal**: Existing single-user installs migrate to system-wide without data loss.

**File(s):** `bin/migrate-to-system.sh` (new), `teleclaude/core/migrations/`

- [ ] Detect existing single-user layout
- [ ] Copy/move database to system location
- [ ] Split config into system/secrets/personal layers
- [ ] Re-assign existing sessions to the migrating user
- [ ] Move shared docs/snippets to system location
- [ ] Validate migration: verify daemon starts, sessions accessible, config loads
- [ ] Rollback guide: document how to revert if migration fails
- [ ] Tests: migration on sample data, idempotency, rollback verification

**Dependencies**: Phase 5 (system layout must exist as the migration target).

---

## Phase Dependency Graph

```
Phase 1: Identity Resolution
    ↓
Phase 2: Session Ownership (depends on 1)
    ↓
Phase 3: Admin Audit (depends on 2)

Phase 1: Identity Resolution
    ↓
Phase 4: Config Separation (depends on 1)
    ↓
Phase 5: Service User (depends on 4)
    ↓
Phase 6: Migration (depends on 5)
```

Phases 2-3 and 4-6 can proceed in parallel after Phase 1.

## Open Design Questions (Must Resolve Before Phase Builds)

1. **Socket location in system mode**: `/tmp/teleclaude.sock` (current) vs `/var/run/teleclaude/teleclaude.sock`? The latter is more conventional but requires directory creation at boot.
2. **Per-user database or shared**: Input suggests shared DB. SQLite WAL handles concurrent readers well. The existing command queue serializes writes. Keep single DB unless write contention proves problematic.
3. **Agent credential model**: Daemon holds all API keys centrally. Users don't need keys. But if a user wants to run `claude` directly outside TeleClaude, they need their own key. This is explicitly out of scope.
4. **Cost allocation**: Session metadata already includes `thinking_mode` and `active_agent`. Token counting is not yet implemented. Defer to a separate todo.
5. **Worktree coordination**: Two users on the same project need separate worktrees. The existing worktree system is per-session. Document this as a limitation; full coordination is a separate concern.

## Validation Strategy

Each phase has its own test suite. Integration testing across phases:

- Phase 1+2: Two OS users create sessions; each sees only their own.
- Phase 2+3: Admin views all sessions; transcript access is logged.
- Phase 4+5: Daemon starts from system config under service user.
- Phase 5+6: Migrate existing install; verify all sessions and config survive.

## Risk Mitigation

- **Incremental delivery**: Each phase is independently useful and mergeable.
- **No big-bang migration**: System-wide mode is opt-in. Single-user mode continues to work.
- **Platform abstraction**: macOS/Linux differences isolated in a platform module.
