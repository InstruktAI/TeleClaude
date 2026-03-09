# Implementation Plan: Session Ownership & Visibility

## Overview

Add ownership to every session and filter visibility by the caller's role. This builds on the identity resolution from Phase 1 and requires dialect-aware migrations from Phase 0. The existing `_filter_sessions_by_role()` in the API server already implements the pattern — this phase extends it to use socket-resolved identity and adds TUI owner badges.

## Phase 1: Core Changes

### Task 1.1: Add ownership columns

**File(s):** `teleclaude/core/db_models.py`, `teleclaude/core/schema.sql`, `teleclaude/core/migrations/` (new migration)

- [ ] Add `owner_person: Optional[str] = None` and `owner_uid: Optional[int] = None` to `db_models.Session`
- [ ] Add columns to `schema.sql` for fresh installs
- [ ] Write dialect-aware migration (must work on both SQLite and PostgreSQL)
- [ ] Default: NULL (existing sessions pre-migration)

### Task 1.2: Populate ownership on session creation

**File(s):** `teleclaude/core/session_launcher.py`, `teleclaude/core/command_handlers.py`

- [ ] When creating a session, read `CallerIdentity` from command context
- [ ] Set `owner_person` and `owner_uid` on the new session row
- [ ] For adapter-originated sessions (Telegram, Discord): set owner from adapter identity
- [ ] For sessions without identity context: leave NULL (backward compatibility)

### Task 1.3: Update API session filtering

**File(s):** `teleclaude/api_server.py`

- [ ] Extend `_filter_sessions_by_role()` to use socket-resolved identity when available
- [ ] Admin: all sessions (existing behavior)
- [ ] Member: sessions where `owner_person` matches caller OR `owner_person IS NULL` (pre-migration)
- [ ] Public: empty list
- [ ] Preserve HTTP header fallback for TUI (until TUI also uses socket identity)

### Task 1.4: Update MCP session listing

**File(s):** `teleclaude/mcp/handlers.py`

- [ ] `list_sessions` tool: apply role-based filtering using caller identity from command context
- [ ] Respect same visibility rules as API

### Task 1.5: TUI owner badges

**File(s):** `teleclaude/cli/tui/views/sessions.py`

- [ ] In `_format_session()`: if session has `owner_person` different from current user, show badge
- [ ] Badge format: `[owner_name]` appended to session title line
- [ ] Only show badges when in multi-user mode (more than one person configured)

### Task 1.6: Session start audit notice

**File(s):** `teleclaude/core/session_launcher.py` or `teleclaude/core/tmux_bridge.py`

- [ ] After session creation, inject notice text into the tmux pane: "Sessions on this system are subject to admin audit."
- [ ] Only show in multi-user mode
- [ ] Notice is informational, not interactive

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Unit test: session creation with CallerIdentity → ownership populated
- [ ] Unit test: session creation without identity → NULL ownership
- [ ] Unit test: `_filter_sessions_by_role()` — admin sees all, member sees own, public sees none
- [ ] Unit test: pre-migration sessions (NULL owner) visible to admin
- [ ] Unit test: TUI badge formatting
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly
