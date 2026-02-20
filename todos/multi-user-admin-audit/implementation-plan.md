# Implementation Plan: Admin Observability & Audit

## Overview

Add an audit trail for admin transcript access and gate transcript reads by caller role. The approach: new `AuditLog` SQLModel, audit service for logging and querying, role checks on transcript API endpoints, and TUI gating with visual indicators.

## Phase 1: Core Changes

### Task 1.1: Audit log model and migration

**File(s):** `teleclaude/core/db_models.py`, `teleclaude/core/schema.sql`, `teleclaude/core/migrations/` (new)

- [ ] Add `AuditLog` SQLModel:
  ```
  id: int (PK, autoincrement)
  actor_person: str (who accessed)
  actor_uid: int (OS UID)
  action_type: str ("transcript_read", "transcript_export", etc.)
  target_session_id: str (FK to sessions)
  target_owner_person: str (whose session)
  created_at: datetime
  ```
- [ ] Add to `schema.sql` for fresh installs
- [ ] Dialect-aware migration

### Task 1.2: Audit service

**File(s):** `teleclaude/services/audit_service.py` (new)

- [ ] `log_access(actor: CallerIdentity, action: str, session: Session) -> None`
  - Skip logging if actor is accessing own session
  - Insert audit_log row
- [ ] `query_audit_log(actor: CallerIdentity, filters: dict) -> list[AuditLogEntry]`
  - Only admin can query
  - Filter by target_session_id, time range, action_type

### Task 1.3: Transcript API role gating

**File(s):** `teleclaude/api_server.py`

- [ ] Transcript/output endpoints: check caller identity
- [ ] Own session: allow (no audit log)
- [ ] Admin accessing other's session: allow + audit log
- [ ] Non-admin accessing other's session: 403 Forbidden
- [ ] Audit log query endpoint (admin only)

### Task 1.4: TUI transcript gating

**File(s):** `teleclaude/cli/tui/views/sessions.py`, `teleclaude/cli/tui/pane_manager.py`

- [ ] When admin selects another user's session, show confirmation before displaying transcript
- [ ] Visual indicator in session pane: "Viewing [owner]'s session — access logged"
- [ ] Keybinding for explicit transcript access (e.g., `Enter` still works but shows notice)

### Task 1.5: MCP tool gating

**File(s):** `teleclaude/mcp/handlers.py`

- [ ] `get_session_data` tool: apply same role-based gating + audit logging
- [ ] Return error for non-admin accessing other's session

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Unit test: `log_access()` creates audit row for cross-user access
- [ ] Unit test: `log_access()` skips logging for own-session access
- [ ] Unit test: non-admin transcript request → 403
- [ ] Unit test: admin transcript request → allowed + audit row
- [ ] Unit test: audit log query returns correct results
- [ ] Unit test: audit log is append-only (no delete/update)
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly
