# DB Refactor: Eliminate ux_state JSON Blob

## Problem Statement

The `ux_state` column in the `sessions` table stores a JSON blob with 14 fields. This causes:

1. **Typing pain** - Requires `from_dict()` / `to_dict()` conversions, `_UNSET` sentinel values, type casting
2. **Boilerplate** - 369 lines in `ux_state.py` just to read/write session properties
3. **Query limitations** - Can't easily filter/sort by fields inside the JSON
4. **Hidden schema** - Field names and types not visible in database schema

## Goal

Replace `ux_state` JSON blob with proper columns on the `sessions` table, and normalize list fields into a separate table.

## Current State

```python
# ux_state.py - SessionUXState dataclass
@dataclass
class SessionUXState:
    output_message_id: Optional[str] = None
    pending_deletions: list[str] = field(default_factory=list)
    pending_feedback_deletions: list[str] = field(default_factory=list)
    last_input_adapter: Optional[str] = None
    notification_sent: bool = False
    native_session_id: Optional[str] = None
    native_log_file: Optional[str] = None
    active_agent: Optional[str] = None
    thinking_mode: Optional[str] = None
    native_tty_path: Optional[str] = None
    tmux_tty_path: Optional[str] = None
    native_pid: Optional[int] = None
    tui_log_file: Optional[str] = None
    tui_capture_started: bool = False
```

## Target State

### Sessions Table - New Columns

| Column | Type | Description |
|--------|------|-------------|
| `output_message_id` | TEXT | Current output message ID in UI |
| `last_input_adapter` | TEXT | Adapter that last received user input |
| `notification_sent` | INTEGER | Agent notification hook flag (0/1) |
| `native_session_id` | TEXT | Native agent session ID (e.g., Claude session ID) |
| `native_log_file` | TEXT | Path to native agent .jsonl log |
| `active_agent` | TEXT | Name of active agent: "claude", "gemini", "codex" |
| `thinking_mode` | TEXT | Model tier: "fast", "med", "slow" |
| `native_tty_path` | TEXT | TTY path for agent CLI (non-tmux) |
| `tmux_tty_path` | TEXT | tmux pane TTY path (terminal-origin sessions) |
| `native_pid` | INTEGER | Parent PID for agent CLI |
| `tui_log_file` | TEXT | Path to raw TUI output log |
| `tui_capture_started` | INTEGER | Whether TUI capture was initiated (0/1) |
| `last_message_sent` | TEXT | Last user message sent to session |
| `last_message_sent_at` | TEXT | Timestamp of last message sent |
| `last_feedback_received` | TEXT | Last feedback/summary from agent |
| `last_feedback_received_at` | TEXT | Timestamp of last feedback |

### New Table - pending_message_deletions

Replaces `pending_deletions` and `pending_feedback_deletions` lists:

```sql
CREATE TABLE pending_message_deletions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    message_id TEXT NOT NULL,
    deletion_type TEXT NOT NULL CHECK(deletion_type IN ('user_input', 'feedback')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, message_id, deletion_type)
);
```

## Success Criteria

- [ ] All 12 scalar ux_state fields are columns on sessions table
- [ ] 4 new session visibility fields added (last_message_*, last_feedback_*)
- [ ] List fields migrated to pending_message_deletions table
- [ ] All code updated to use direct column access
- [ ] ux_state column dropped from sessions table
- [ ] ux_state.py reduced to SystemUXState only (or deleted entirely)
- [ ] All tests pass
- [ ] No JSON serialization for session UX state

## Out of Scope

- `adapter_metadata` JSON blob (intentionally kept - useful for adapter routing)
- `SystemUXState` (small, rarely changes, can stay as-is or be addressed separately)
- Queue refactoring (separate todo)

## Dependencies

- None (self-contained refactoring)

## Dependents

- telec-mcp (benefits from direct column access for session listing)
- Any future reporting/querying on session state
