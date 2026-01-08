# Implementation Plan: DB Refactor

## Overview

Migrate `ux_state` JSON blob to proper columns. Total estimated effort: ~4-6 hours.

## Phase 1: Schema Migration

### 1.1 Add New Columns to Sessions Table

Update `teleclaude/core/schema.sql`:

```sql
-- Existing sessions table gets new columns
-- (SQLite doesn't support ADD COLUMN in a single statement, so run separately)

ALTER TABLE sessions ADD COLUMN output_message_id TEXT;
ALTER TABLE sessions ADD COLUMN last_input_adapter TEXT;
ALTER TABLE sessions ADD COLUMN notification_sent INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN native_session_id TEXT;
ALTER TABLE sessions ADD COLUMN native_log_file TEXT;
ALTER TABLE sessions ADD COLUMN active_agent TEXT;
ALTER TABLE sessions ADD COLUMN thinking_mode TEXT;
ALTER TABLE sessions ADD COLUMN native_tty_path TEXT;
ALTER TABLE sessions ADD COLUMN tmux_tty_path TEXT;
ALTER TABLE sessions ADD COLUMN native_pid INTEGER;
ALTER TABLE sessions ADD COLUMN tui_log_file TEXT;
ALTER TABLE sessions ADD COLUMN tui_capture_started INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN last_message_sent TEXT;
ALTER TABLE sessions ADD COLUMN last_message_sent_at TEXT;
ALTER TABLE sessions ADD COLUMN last_feedback_received TEXT;
ALTER TABLE sessions ADD COLUMN last_feedback_received_at TEXT;
```

### 1.2 Create pending_message_deletions Table

```sql
CREATE TABLE IF NOT EXISTS pending_message_deletions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    deletion_type TEXT NOT NULL CHECK(deletion_type IN ('user_input', 'feedback')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, message_id, deletion_type),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pending_deletions_session
    ON pending_message_deletions(session_id);
```

### 1.3 Migration Script

Create `teleclaude/core/migrations/001_ux_state_to_columns.py`:

```python
"""Migrate ux_state JSON to columns."""

import json
import aiosqlite

async def migrate(db: aiosqlite.Connection) -> None:
    """Migrate ux_state JSON blob to columns."""

    # Fetch all sessions with ux_state
    cursor = await db.execute("SELECT session_id, ux_state FROM sessions WHERE ux_state IS NOT NULL")
    rows = await cursor.fetchall()

    for row in rows:
        session_id = row[0]
        ux_state_raw = row[1]

        if not ux_state_raw:
            continue

        try:
            ux = json.loads(ux_state_raw)
        except json.JSONDecodeError:
            continue

        # Update scalar columns
        await db.execute("""
            UPDATE sessions SET
                output_message_id = ?,
                last_input_adapter = ?,
                notification_sent = ?,
                native_session_id = ?,
                native_log_file = ?,
                active_agent = ?,
                thinking_mode = ?,
                native_tty_path = ?,
                tmux_tty_path = ?,
                native_pid = ?,
                tui_log_file = ?,
                tui_capture_started = ?
            WHERE session_id = ?
        """, (
            ux.get("output_message_id"),
            ux.get("last_input_adapter"),
            1 if ux.get("notification_sent") else 0,
            ux.get("native_session_id"),
            ux.get("native_log_file"),
            ux.get("active_agent"),
            ux.get("thinking_mode"),
            ux.get("native_tty_path"),
            ux.get("tmux_tty_path"),
            ux.get("native_pid"),
            ux.get("tui_log_file"),
            1 if ux.get("tui_capture_started") else 0,
            session_id,
        ))

        # Migrate pending_deletions list
        for msg_id in ux.get("pending_deletions", []):
            await db.execute("""
                INSERT OR IGNORE INTO pending_message_deletions
                    (session_id, message_id, deletion_type)
                VALUES (?, ?, 'user_input')
            """, (session_id, msg_id))

        # Migrate pending_feedback_deletions list
        for msg_id in ux.get("pending_feedback_deletions", []):
            await db.execute("""
                INSERT OR IGNORE INTO pending_message_deletions
                    (session_id, message_id, deletion_type)
                VALUES (?, ?, 'feedback')
            """, (session_id, msg_id))

    await db.commit()
```

## Phase 2: Update db.py

### 2.1 Add Helper Methods

```python
# teleclaude/core/db.py

async def update_session_fields(self, session_id: str, **fields: object) -> None:
    """Update arbitrary session fields."""
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [session_id]
    await self._db.execute(
        f"UPDATE sessions SET {set_clause}, last_activity = CURRENT_TIMESTAMP WHERE session_id = ?",
        values,
    )
    await self._db.commit()

async def get_pending_deletions(self, session_id: str, deletion_type: str) -> list[str]:
    """Get pending message deletions for a session."""
    cursor = await self._db.execute(
        "SELECT message_id FROM pending_message_deletions WHERE session_id = ? AND deletion_type = ?",
        (session_id, deletion_type),
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]

async def add_pending_deletion(self, session_id: str, message_id: str, deletion_type: str) -> None:
    """Add a pending message deletion."""
    await self._db.execute(
        "INSERT OR IGNORE INTO pending_message_deletions (session_id, message_id, deletion_type) VALUES (?, ?, ?)",
        (session_id, message_id, deletion_type),
    )
    await self._db.commit()

async def clear_pending_deletions(self, session_id: str, deletion_type: str) -> list[str]:
    """Clear and return pending deletions for a session."""
    message_ids = await self.get_pending_deletions(session_id, deletion_type)
    await self._db.execute(
        "DELETE FROM pending_message_deletions WHERE session_id = ? AND deletion_type = ?",
        (session_id, deletion_type),
    )
    await self._db.commit()
    return message_ids
```

### 2.2 Update Session Model

```python
# teleclaude/core/models.py - Update Session dataclass

@dataclass
class Session:
    session_id: str
    computer_name: str
    title: str
    tmux_session_name: str
    origin_adapter: str
    adapter_metadata: dict[str, object] | None  # Keep as JSON - useful for routing
    created_at: datetime
    last_activity: datetime
    terminal_size: str
    working_directory: str
    description: str | None
    initiated_by_ai: bool
    # New columns (previously in ux_state)
    output_message_id: str | None = None
    last_input_adapter: str | None = None
    notification_sent: bool = False
    native_session_id: str | None = None
    native_log_file: str | None = None
    active_agent: str | None = None
    thinking_mode: str | None = None
    native_tty_path: str | None = None
    tmux_tty_path: str | None = None
    native_pid: int | None = None
    tui_log_file: str | None = None
    tui_capture_started: bool = False
    last_message_sent: str | None = None
    last_message_sent_at: datetime | None = None
    last_feedback_received: str | None = None
    last_feedback_received_at: datetime | None = None
```

## Phase 3: Update All Callers

### 3.1 Files to Update

Search and replace pattern: `get_session_ux_state` and `update_session_ux_state`

| File | Changes |
|------|---------|
| `teleclaude/daemon.py` | Replace ux_state calls with direct db.update_session_fields() |
| `teleclaude/core/command_handlers.py` | Replace ux_state calls |
| `teleclaude/core/adapter_client.py` | Replace ux_state calls |
| `teleclaude/adapters/ui_adapter.py` | Replace ux_state calls for pending deletions |
| `teleclaude/adapters/telegram_adapter.py` | Replace ux_state calls |
| `teleclaude/cli/telec.py` | Update session loading (already reads from sessions table) |
| `teleclaude/hooks/receiver.py` | Replace ux_state calls |
| `teleclaude/core/agent_coordinator.py` | Replace ux_state calls |
| `teleclaude/mcp/handlers.py` | Update list_sessions to include new fields |

### 3.2 Example Transformation

**Before:**
```python
from teleclaude.core.ux_state import get_session_ux_state, update_session_ux_state

ux = await get_session_ux_state(db._db, session_id)
if ux.active_agent:
    # ...

await update_session_ux_state(db._db, session_id, active_agent="claude", thinking_mode="slow")
```

**After:**
```python
session = await db.get_session(session_id)
if session and session.active_agent:
    # ...

await db.update_session_fields(session_id, active_agent="claude", thinking_mode="slow")
```

**For pending deletions - Before:**
```python
ux = await get_session_ux_state(db._db, session_id)
pending = ux.pending_deletions
await update_session_ux_state(db._db, session_id, pending_deletions=[])
```

**After:**
```python
pending = await db.clear_pending_deletions(session_id, "user_input")
```

## Phase 4: Cleanup

### 4.1 Update schema.sql

Remove ux_state from CREATE TABLE, add new columns inline:

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT,
    tmux_session_name TEXT NOT NULL,
    origin_adapter TEXT NOT NULL DEFAULT 'telegram',
    adapter_metadata TEXT,  -- Keep as JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    terminal_size TEXT DEFAULT '80x24',
    working_directory TEXT DEFAULT '~',
    description TEXT,
    initiated_by_ai BOOLEAN DEFAULT 0,
    -- UX state fields (previously JSON blob)
    output_message_id TEXT,
    last_input_adapter TEXT,
    notification_sent INTEGER DEFAULT 0,
    native_session_id TEXT,
    native_log_file TEXT,
    active_agent TEXT,
    thinking_mode TEXT,
    native_tty_path TEXT,
    tmux_tty_path TEXT,
    native_pid INTEGER,
    tui_log_file TEXT,
    tui_capture_started INTEGER DEFAULT 0,
    last_message_sent TEXT,
    last_message_sent_at TEXT,
    last_feedback_received TEXT,
    last_feedback_received_at TEXT,
    UNIQUE(computer_name, tmux_session_name)
);
```

### 4.2 Reduce ux_state.py

Keep only `SystemUXState` (or delete entirely if not needed):

```python
# teleclaude/core/ux_state.py - minimal version

"""System UX state management."""

import json
from dataclasses import dataclass, field
from typing import Optional

import aiosqlite


@dataclass
class RegistryState:
    topic_id: Optional[int] = None
    ping_message_id: Optional[int] = None
    pong_message_id: Optional[int] = None


@dataclass
class SystemUXState:
    registry: RegistryState = field(default_factory=RegistryState)

    # ... keep from_dict, to_dict, get/update functions for system state only
```

Delete `SessionUXState`, `UXStatePayload`, and all session-related functions.

### 4.3 Update Tests

- Update `tests/unit/test_ux_state.py` - remove session tests or update to test columns
- Update `tests/unit/test_db.py` - add tests for new helper methods
- Update any test that mocks ux_state

## Phase 5: Verification

### 5.1 Run Tests

```bash
make test-unit
make test-e2e
make lint
```

### 5.2 Manual Verification

1. Start daemon with existing database (migration runs)
2. Create new session, verify fields populate
3. Check pending deletions work
4. Verify telec /list shows sessions correctly

## Rollback Plan

If issues arise:
1. Keep ux_state column (don't drop until verified in production)
2. Migration is additive (new columns + table), doesn't delete data
3. Can revert code while keeping new schema

## Checklist

- [ ] Update schema.sql with new columns
- [ ] Create pending_message_deletions table
- [ ] Write migration script
- [ ] Update db.py with helper methods
- [ ] Update Session model
- [ ] Update daemon.py (~15 call sites)
- [ ] Update command_handlers.py (~10 call sites)
- [ ] Update adapter_client.py (~5 call sites)
- [ ] Update ui_adapter.py (~8 call sites)
- [ ] Update telegram_adapter.py (~3 call sites)
- [ ] Update agent_coordinator.py (~2 call sites)
- [ ] Update hooks/receiver.py (~2 call sites)
- [ ] Update mcp/handlers.py (list_sessions)
- [ ] Update telec.py
- [ ] Reduce ux_state.py to system-only
- [ ] Update tests
- [ ] Run full test suite
- [ ] Manual verification
- [ ] Drop ux_state column (after production verification)
