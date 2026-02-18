# Requirements: Multi-User System-Wide Installation

## Goal

Transform TeleClaude from a single-user, per-project installation into a system-wide service that supports multiple OS users on the same machine. Each user has their own identity, role, sessions, and personal config. The admin has operational oversight of all system activity.

## Problem Statement

Today, TeleClaude is installed under one user's home directory. The daemon runs as that user. The MCP socket has no caller authentication. All sessions live in one database with no ownership scoping. Config (including secrets) is a single file. This model cannot serve a shared machine where multiple people need independent access to the AI platform.

## Why Now

The role system (`admin`, `member`, `contributor`, `newcomer`) and doc-access-control (role-based snippet filtering) are already delivered. These are the authorization primitives. What's missing is the deployment and authentication model to actually serve multiple people.

## In Scope

1. **OS user identity binding** — Map OS users to TeleClaude persons via UID resolution on Unix socket connections.
2. **Session ownership** — Every session has an owner. Visibility is role-scoped: admin sees all metadata, members see only their own sessions.
3. **Admin observability** — Admin sees session list/metadata always. Transcript access is explicit and audited. Users see a notice at session start.
4. **Config separation** — Split into system config (people, projects, adapters), secrets (API keys, tokens), and per-user config (preferences).
5. **Service user model** — Daemon runs under a dedicated `teleclaude` service user, managed by `launchd` (macOS) or `systemd` (Linux).
6. **System-wide directory layout** — Shared resources at `/usr/local/share/teleclaude/`, per-user data at `~/.teleclaude/`.
7. **File permissions** — Proper ownership and access control for shared resources, database, secrets, and per-user directories.
8. **Migration tooling** — Non-destructive migration from existing single-user install to system-wide layout.

## Out of Scope

- Web-based multi-user access (covered by `web-interface` todos).
- Remote multi-machine access (existing Redis/peer system).
- Billing or subscription management.
- User self-registration (admin manages people in config).
- Per-user API keys or credential proxy (deferred; daemon holds keys centrally).
- SQLite-to-PostgreSQL migration (deferred; evaluate if write contention becomes a real problem).

## Success Criteria

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
- [ ] Existing single-user installs can migrate to system-wide without data loss.
- [ ] External adapters (Telegram, Discord) continue to resolve identity as today (chat ID → person → role) — no change needed.

## Constraints

- Must support both macOS (`launchd`, `LOCAL_PEERCRED`) and Linux (`systemd`, `SO_PEERCRED`).
- SQLite remains the database engine. Single shared DB owned by the service user. WAL mode for concurrent readers.
- Daemon still enforces single-instance via SQLite exclusive lock.
- Doc snippet access control already works via role comparison — no changes needed there.
- The TUI grouping remains project-first (not person-first). No separate "people" tab — that's surveillance UX.

## Risks

- **SQLite write contention**: Multiple users generating sessions simultaneously may stress SQLite's single-writer model. Mitigation: WAL mode, command queue serialization (already in place), monitor write latency.
- **macOS vs Linux divergence**: Socket credential APIs and service management differ. Mitigation: Abstract behind a platform module with clean interfaces.
- **Migration complexity**: Moving from per-project DB to system-wide DB requires careful data migration. Mitigation: Build migration tool incrementally, test on a copy first.
- **Worktree conflicts**: Two users on the same project may collide on worktrees. Mitigation: Document coordination expectations; full isolation is out of scope for first pass.

## Design Decisions (From Input)

1. **Observable metadata, gated content**: Admin always sees session list/metadata. Transcript access is explicit, logged, and auditable. No ambient surveillance.
2. **No private sessions**: The shared system is a shared resource. Privacy = use your own machine.
3. **Project-first grouping**: TUI shows sessions grouped by project with owner badges. No person-first views.
4. **Unix socket auth**: Kernel-level peer credentials. No passwords, no tokens for local users.
5. **Central API keys**: Daemon holds all API keys. Users don't need their own keys.

## Dependencies

- `doc-access-control` — DELIVERED. Role-based snippet filtering is ready.
- Session identity model — stable and working.
- People/identity configuration — exists in config schema.
