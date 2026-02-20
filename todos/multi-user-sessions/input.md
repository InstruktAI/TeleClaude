# Session Ownership & Visibility

## Origin

Extracted from `multi-user-system-install` Phase 2. Once the daemon knows WHO is connecting (Phase 1), every session needs an owner and visibility must be role-scoped.

## What We Have Today

- Sessions table has `human_email` and `human_role` columns (from help desk identity flow)
- Sessions table has `visibility TEXT DEFAULT 'private'` column
- `_filter_sessions_by_role()` in `api_server.py` already does role-based filtering using HTTP headers
- TUI sessions view groups by project with tree rendering
- Session creation in `session_launcher.py` has no ownership assignment
- MCP tools list all sessions without filtering

## What Needs to Change

### 1. Ownership Columns

Add `owner_person TEXT` and `owner_uid INTEGER` to sessions table. Populated from `CallerIdentity` at session creation time.

### 2. Visibility Rules

- Admin sees ALL sessions (metadata always, transcripts gated — Phase 3)
- Member sees their OWN sessions only
- Contributor/newcomer sees their OWN sessions only
- Public sees nothing

### 3. TUI Owner Badges

Admin view shows owner badge on sessions belonging to other users. Project-first grouping preserved (not person-first — that's surveillance UX).

### 4. Session Start Notice

Every session shows: "Sessions on this system are subject to admin audit."

### 5. API/MCP Filtering

Extend `_filter_sessions_by_role()` to use socket-resolved identity instead of HTTP headers. MCP tool `list_sessions` respects caller role.

## Dependencies

- Phase 0: db-abstraction (migrations must work on both backends)
- Phase 1: identity (CallerIdentity must exist to populate ownership)
