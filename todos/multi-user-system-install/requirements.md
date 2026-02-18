# Requirements: Multi-User System-Wide Installation

## Goal

Transform TeleClaude from a single-user, per-project installation into a system-wide service that supports multiple OS users on the same machine. Each user has their own identity, role, sessions, and personal config. The admin has operational oversight of all system activity.

## Problem Statement

Today, TeleClaude is installed under one user's home directory. The daemon runs as that user. The MCP socket has no caller authentication. All sessions live in one database with no ownership scoping. Config (including secrets) is a single file. This model cannot serve a shared machine where multiple people need independent access to the AI platform.

## Why Now

The role system (`admin`, `member`, `contributor`, `newcomer`) and doc-access-control (role-based snippet filtering) are already delivered. These are the authorization primitives. What's missing is the deployment and authentication model to actually serve multiple people.

## In Scope

1. **Database backend abstraction** — Support both SQLite (single-user, default) and PostgreSQL (multi-user). Config selects engine at startup. The codebase already uses SQLAlchemy/SQLModel; the main work is making engine creation configurable and handling dialect-specific operations.
2. **OS user identity binding** — Map OS users to TeleClaude persons via UID resolution on Unix socket connections.
3. **Session ownership** — Every session has an owner. Visibility is role-scoped: admin sees all metadata, members see only their own sessions.
4. **Admin observability** — Admin sees session list/metadata always. Transcript access is explicit and audited. Users see a notice at session start.
5. **Config separation** — Split into system config (people, projects, adapters), secrets (API keys, tokens), and per-user config (preferences).
6. **Service user model** — Daemon runs under a dedicated `teleclaude` service user, managed by `launchd` (macOS) or `systemd` (Linux).
7. **System-wide directory layout** — Shared resources at `/usr/local/share/teleclaude/`, per-user data at `~/.teleclaude/`.
8. **File permissions** — Proper ownership and access control for shared resources, database, secrets, and per-user directories.
9. **Migration tooling** — Non-destructive migration from existing single-user SQLite install to system-wide PostgreSQL layout.

## Out of Scope

- Web-based multi-user access (covered by `web-interface` todos).
- Remote multi-machine access (existing Redis/peer system).
- Billing or subscription management.
- User self-registration (admin manages people in config).
- Per-user API keys or credential proxy (deferred; daemon holds keys centrally).
- Bundling PostgreSQL — multi-user mode requires an external Postgres install (system package, Docker Compose, or managed service). TeleClaude's installer creates the database and role, not the Postgres server.

## Success Criteria

- [ ] Single-user mode continues to work exactly as today with SQLite (zero config, zero extra dependencies).
- [ ] Multi-user mode uses PostgreSQL. Config specifies `database: { engine: postgresql, host: ..., dbname: teleclaude }`.
- [ ] CI tests run against both SQLite and PostgreSQL backends.
- [ ] Multiple OS users on the same machine can each run `telec` and get their own sessions.
- [ ] Unix socket peer credentials (`SO_PEERCRED`/`LOCAL_PEERCRED`) resolve connecting UID to a TeleClaude person and role.
- [ ] Unknown UIDs are treated as `public` (least privilege, no session creation).
- [ ] Each session records its owner (person name + UID).
- [ ] Admin can see all sessions in TUI (metadata view with owner badges, grouped by project).
- [ ] Admin transcript access is an explicit action that is logged in an audit trail.
- [ ] Session start shows a notice: "Sessions on this system are subject to admin audit."
- [ ] API keys and adapter tokens live in a secrets file readable only by root/service user.
- [ ] Per-user config (`~/.teleclaude/config.yml`) holds only personal preferences, no secrets.
- [ ] Daemon runs as a dedicated `teleclaude` service user with proper systemd/launchd unit.
- [ ] Existing single-user installs can migrate to system-wide without data loss (SQLite → PostgreSQL data migration included).
- [ ] External adapters (Telegram, Discord) continue to resolve identity as today (chat ID → person → role) — no change needed.

## Constraints

- Must support both macOS (`launchd`, `LOCAL_PEERCRED`) and Linux (`systemd`, `SO_PEERCRED`).
- SQLite remains the default for single-user. PostgreSQL is required for multi-user.
- Both backends use the same SQLAlchemy/SQLModel models. Dialect-specific operations (PRAGMAs, upserts) are conditionally handled.
- Daemon still enforces single-instance (SQLite: exclusive lock; PostgreSQL: advisory lock).
- Doc snippet access control already works via role comparison — no changes needed there.
- The TUI grouping remains project-first (not person-first). No separate "people" tab — that's surveillance UX.
- PostgreSQL is NOT bundled. The installer checks for it, creates the `teleclaude` database and role. Docker Compose is the easy option for users who don't want to manage Postgres themselves.

## Risks

- **SQLAlchemy dialect gaps**: Some queries may use SQLite-specific syntax (e.g., `sqlite_insert` for upsert). Each must be converted to dialect-aware alternatives. Mitigation: audit all raw SQL and dialect-specific imports.
- **Migration runner**: Current migrations are raw SQL (`aiosqlite`). Must be converted to SQLAlchemy DDL or Alembic. Mitigation: phase this into the database abstraction work.
- **macOS vs Linux divergence**: Socket credential APIs and service management differ. Mitigation: abstract behind a platform module.
- **Migration data fidelity**: SQLite → PostgreSQL data migration must preserve all session state, memory, hooks. Mitigation: validation step compares row counts and checksums.
- **Worktree conflicts**: Two users on the same project may collide on worktrees. Mitigation: document coordination expectations; full isolation is out of scope for first pass.

## Design Decisions

1. **Dual database backends**: SQLite for single-user (zero-config), PostgreSQL for multi-user (concurrent writes, proper auth). Config selects at startup.
2. **Observable metadata, gated content**: Admin always sees session list/metadata. Transcript access is explicit, logged, and auditable. No ambient surveillance.
3. **No private sessions**: The shared system is a shared resource. Privacy = use your own machine.
4. **Project-first grouping**: TUI shows sessions grouped by project with owner badges. No person-first views.
5. **Unix socket auth**: Kernel-level peer credentials. No passwords, no tokens for local users.
6. **Central API keys**: Daemon holds all API keys. Users don't need their own keys.
7. **No bundled Postgres**: Standard external dependency pattern (like Django, GitLab, Discourse).

## Dependencies

- `doc-access-control` — DELIVERED. Role-based snippet filtering is ready.
- Session identity model — stable and working.
- People/identity configuration — exists in config schema.
- SQLAlchemy/SQLModel — already in use. PostgreSQL support requires `asyncpg` driver addition.
