# Requirements: Admin Observability & Audit

## Goal

Admin can access any session's transcript explicitly, and every such access is logged in an audit trail. Non-admin users cannot access transcripts belonging to other users. The system provides operational transparency without ambient surveillance.

## Problem Statement

In a multi-user deployment, the admin needs to inspect session activity for operational reasons (debugging, quality review, incident response). But transcripts contain thinking, half-formed ideas, and personal questions — more intimate than command history. Access must be explicit, audited, and visible to users.

## In Scope

1. **Audit log table** — `audit_log` with who, what, when, target_session_id, action_type.
2. **Transcript access gating** — API endpoint checks caller role before serving transcripts.
3. **Audit logging** — Every admin transcript access creates an audit_log row.
4. **TUI transcript gating** — Admin must take explicit action to view another user's transcript.
5. **Audit log viewer** — Admin can query the audit trail.

## Out of Scope

- Session metadata visibility (covered by Phase 2 — admin already sees all session metadata).
- Real-time transcript streaming restrictions (initial implementation gates on-demand reads).
- Audit log export or compliance reporting tools.

## Success Criteria

- [ ] `audit_log` table exists with columns: id, actor_person, action_type, target_session_id, timestamp.
- [ ] Admin reads another user's transcript → audit_log row created.
- [ ] Admin reads own transcript → no audit_log row (not a cross-user access).
- [ ] Member requests another user's transcript via API → 403 Forbidden.
- [ ] TUI: viewing another user's transcript requires explicit keybinding/action.
- [ ] TUI: visual indicator when viewing another user's session ("Viewing [alice]'s session").
- [ ] Admin can query audit_log (API endpoint and/or TUI view).
- [ ] Audit log rows are immutable (no delete/update API).

## Constraints

- Audit log is append-only. No endpoint to delete or modify audit entries.
- Audit logging must not add noticeable latency to transcript reads.
- Both SQLite and PostgreSQL backends.

## Dependencies

- Phase 2: `multi-user-sessions` — session ownership required to determine "whose transcript."
