# Admin Observability & Audit

## Origin

Extracted from `multi-user-system-install` Phase 3. The admin needs operational visibility without ambient surveillance. Session metadata is always visible; transcript access is explicit and audited.

## Design Decision (from parent)

"Observable metadata, gated content." Admin sees session list, owner, timestamp, project, duration, status. Admin does NOT see session transcripts by default. Admin CAN access transcripts — it's an explicit action, and the system logs that access happened.

## What Needs to Change

### 1. Audit Log Table

`audit_log` table: who (person_name), what (action_type), when (timestamp), target (session_id). Every admin transcript read creates a row.

### 2. Transcript Access Gating

API transcript endpoint checks caller role. Non-admin cannot read others' transcripts. Admin can, but it's logged.

### 3. TUI Admin View

Metadata always visible (session list with owner badges — Phase 2). Transcript panel requires explicit action (keybinding). A visual indicator shows when viewing another user's transcript.

### 4. Audit Log Viewer

Admin can query the audit log to see who accessed what.

## Dependencies

- Phase 2: `multi-user-sessions` (session ownership must exist for "whose transcript" to make sense)
