# Requirements: Session Ownership & Visibility

## Goal

Every session records its owner. Session visibility is role-scoped: admin sees all sessions, members see only their own. The TUI shows owner badges for multi-user awareness without surveillance UX.

## Problem Statement

Sessions have no ownership. Any user connecting to the daemon sees all sessions. In a multi-user deployment, a member should only see their own work, while the admin needs operational visibility of system activity.

## In Scope

1. **Ownership columns** — `owner_person TEXT` and `owner_uid INTEGER` on sessions table.
2. **Ownership population** — Set from CallerIdentity when a session is created.
3. **Role-scoped visibility** — Admin sees all; member/contributor/newcomer sees own; public sees nothing.
4. **API filtering** — Extend existing `_filter_sessions_by_role()` to use socket identity.
5. **MCP filtering** — `list_sessions` tool respects caller role.
6. **TUI owner badges** — Admin view shows owner name on sessions belonging to others.
7. **Audit notice** — Session start displays: "Sessions on this system are subject to admin audit."

## Out of Scope

- Transcript access gating (Phase 3: `multi-user-admin-audit`).
- Config separation (Phase 4).
- Person-first grouping in TUI — intentionally excluded (surveillance UX).

## Success Criteria

- [ ] Sessions table has `owner_person` and `owner_uid` columns (migration works on SQLite and PostgreSQL).
- [ ] New sessions created via MCP/TUI have ownership populated from caller identity.
- [ ] Sessions created via external adapters (Telegram, Discord) have ownership from adapter identity.
- [ ] Admin user sees all sessions in TUI and API.
- [ ] Member user sees only their own sessions.
- [ ] Unknown/public caller sees no sessions.
- [ ] TUI shows owner badge (e.g., `[alice]`) on sessions owned by other users in admin view.
- [ ] Session start shows audit notice string.
- [ ] Existing sessions without ownership (pre-migration) remain visible to admin.

## Constraints

- Project-first grouping in TUI is preserved. No "people" tab.
- Migration must handle existing sessions gracefully (NULL owner = visible to admin only).
- Both SQLite and PostgreSQL backends (Phase 0 dependency).

## Dependencies

- Phase 0: `multi-user-db-abstraction` — migration runner must support both backends.
- Phase 1: `multi-user-identity` — CallerIdentity must exist for ownership population.
