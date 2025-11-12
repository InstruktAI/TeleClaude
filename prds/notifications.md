# Claude Code Notification Hook Integration

## Overview

Integrate a notification hook system that sends friendly status messages to TeleClaude sessions when Claude Code becomes ready for user input. This provides a delightful user experience by announcing Claude's availability via randomized messages, while also managing inactivity timers to prevent duplicate notifications.

## Problem Statement

Currently, when Claude Code finishes processing and waits for user input in TeleClaude sessions, there is no notification to the user. This creates a poor UX where users must actively monitor the session to know when Claude is ready. Additionally, the existing inactivity timer system may trigger unnecessary notifications if not coordinated with Claude's readiness state.

## Goals

- Create a notification hook that sends randomized, friendly status messages when Claude becomes ready
- Bootstrap AdapterClient properly to broadcast notifications to all UI adapters
- Track notification state in the database to prevent duplicate messages
- Coordinate with the inactivity timer to avoid conflicting notifications
- Follow TeleClaude's architecture patterns (Module-level Singleton, AdapterClient hub)

## Non-Goals

- TTS (text-to-speech) notifications - the reference hook has this, but we're UI-only
- Custom notification templates per session - use global randomized set
- Notification history tracking - only track current notification state
- User-configurable notification messages - hardcoded set is sufficient

## Technical Approach

### High-Level Design

Create a standalone notification hook script (`.claude/hooks/notification.py`) that:

1. Receives JSON input via stdin (standard Claude Code hook protocol)
2. Bootstraps AdapterClient with config (same pattern as daemon.py)
3. Sends randomized notification message via AdapterClient
4. Updates session UX state to clear inactivity timer flag
5. Exits cleanly with success code

The hook will be registered in Claude Code's settings to trigger on appropriate events (likely `UserPromptSubmit` or similar).

### Key Components

1. **Notification Hook Script** (`.claude/hooks/notification.py`)

   - Standalone Python script using `#!/usr/bin/env -S uv run --script`
   - Reads session_id from stdin JSON payload
   - Bootstraps AdapterClient from config
   - Sends notification via AdapterClient.send_message()
   - Updates UX state to clear inactivity timer

2. **Message Templates**

   - 15+ randomized friendly messages
   - Examples: "Claude is ready...", "Claude reporting back for duty...", "Claude is back baby..."
   - Random selection on each invocation

3. **Inactivity Timer Coordination**
   - Add `notification_sent` flag to ux_state JSON blob
   - Hook sets flag to clear inactivity timer
   - Polling coordinator checks flag and resets timer

### Data Model Changes

**Session UX State Extension** (stored in `ux_state` JSON column):

```python
{
    "output_message_id": str,           # Existing
    "idle_notification_message_id": str, # Existing
    "notification_sent": bool,           # NEW - tracks if hook notification was sent
    "pending_deletions": [str]          # Existing
}
```

**No schema migration needed** - ux_state is already a JSON blob, we just add a new optional field.

### API/Interface Changes

**New Function in `db.py`**:

```python
async def clear_notification_flag(session_id: str) -> None:
    """Clear notification_sent flag in UX state.

    Called by polling coordinator when output resumes to re-enable notifications.
    """
```

**Polling Coordinator Update**:

- Check `notification_sent` flag before starting inactivity timer
- Clear flag when output changes (activity detected)

### Configuration Changes

**No config.yml changes needed** - uses existing config structure.

**Claude Code Hook Registration** (user's `.claude/hooks/` or project `.claude/hooks/`):

```yaml
# Example registration (user adds this to their Claude Code settings)
hooks:
  UserPromptSubmit:
    - command: /path/to/.claude/hooks/notification.py
      args: []
```

## Implementation Details

### Files to Create

- `.claude/hooks/notification.py` - Main notification hook script
  - Shebang: `#!/usr/bin/env -S uv run --script`
  - Dependencies: python-dotenv, pyyaml (existing TeleClaude deps)
  - Bootstrap AdapterClient (similar to daemon.py)
  - Read stdin JSON for session_id
  - Send randomized notification
  - Update UX state via db

### Files to Modify

- `teleclaude/core/db.py`

  - Add `clear_notification_flag(session_id)` helper
  - Add `set_notification_flag(session_id)` helper (used by hook)

- `teleclaude/core/polling_coordinator.py`
  - Import notification flag helpers
  - Check `notification_sent` flag before starting inactivity timer
  - Clear flag when `OutputChanged` event occurs (activity detected)

### Dependencies

**No new dependencies** - uses existing TeleClaude stack:

- python-dotenv (already installed)
- pyyaml (already installed)
- aiosqlite (already installed)

**Runtime Requirements**:

- Hook runs as subprocess via `uv run --script`
- Requires access to `config.yml` and `.env`
- Requires access to `teleclaude.db` (same as daemon)

### Message Templates

```python
NOTIFICATION_MESSAGES = [
    "Claude is ready...",
    "Claude reporting back for duty...",
    "Claude is back baby...",
    "Claude standing by for your next command...",
    "Claude has returned...",
    "Claude is at your service...",
    "Claude awaits your instructions...",
    "Claude ready and waiting...",
    "Claude checking in...",
    "Claude here, what's next?",
    "Claude online and ready...",
    "Claude ready for action...",
    "Claude standing ready...",
    "Claude back in the game...",
    "Claude powered up and ready...",
]
```

### Hook Execution Flow

```
1. Claude Code finishes task → UserPromptSubmit hook triggered
2. Hook script receives JSON via stdin: {"session_id": "abc123", ...}
3. Hook bootstraps AdapterClient from config.yml
4. Hook selects random message from templates
5. Hook sends message via adapter_client.send_message(session_id, message)
6. Hook updates UX state: db.set_notification_flag(session_id, True)
7. Hook exits with code 0

Meanwhile in daemon:
8. Polling coordinator sees notification_sent=True
9. Inactivity timer is paused/reset
10. When output changes, clear notification_sent flag
11. Resume normal inactivity timer behavior
```

### Bootstrapping AdapterClient Pattern

```python
# Similar to daemon.py initialization
from teleclaude.config import load_config
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import init_db

# Load config
config = load_config("config.yml")

# Initialize database
init_db(config.database.path)

# Create AdapterClient (loads all UI adapters)
adapter_client = AdapterClient()
await adapter_client.initialize(config)

# Use adapter_client for notifications
await adapter_client.send_message(session_id, message)
```

## Testing Strategy

### Unit Tests

1. **Test Hook Message Randomization**

   - Verify messages are randomly selected
   - Ensure all 15 messages can be selected

2. **Test UX State Updates**

   - `set_notification_flag()` correctly updates ux_state JSON
   - `clear_notification_flag()` correctly clears flag
   - Flag persists across daemon restarts (DB test)

3. **Test Polling Coordinator Integration**
   - Inactivity timer respects `notification_sent` flag
   - Flag is cleared when output changes
   - IdleDetected events are suppressed when flag is set

### Integration Tests

1. **End-to-End Hook Execution**

   - Create test session
   - Invoke hook script with test JSON
   - Verify notification message appears in session
   - Verify UX state is updated

2. **Inactivity Timer Coordination**
   - Send notification via hook
   - Verify inactivity timer doesn't fire
   - Send output change
   - Verify inactivity timer resumes

### Manual Testing

1. Register hook in Claude Code settings
2. Start TeleClaude session
3. Run Claude Code task
4. Wait for Claude to become ready
5. Verify friendly notification appears
6. Verify no duplicate idle notifications
7. Test across multiple sessions (Telegram + Redis)

## Rollout Plan

### Development and Testing

1. Create hook script with message templates
2. Add UX state helper functions
3. Update polling coordinator with flag logic
4. Write unit tests (db helpers, coordinator logic)
5. Write integration test (hook execution)
6. Manual testing with real sessions

### Deployment Considerations

- **No daemon restart required** - hook is external script
- **Hook registration is user responsibility** - document in README
- **Backward compatible** - `notification_sent` flag is optional in ux_state

### Rollback Strategy

If notification hook causes issues:

1. User removes hook from Claude Code settings
2. No code changes needed - feature is opt-in
3. Existing inactivity timer behavior unchanged

## Success Criteria

- [x] Hook script successfully sends randomized messages to sessions
- [x] AdapterClient properly bootstrapped and broadcasts to all UI adapters
- [x] Inactivity timer coordination prevents duplicate notifications
- [x] UX state flag persists across daemon restarts
- [x] Unit tests achieve >90% coverage for new code
- [x] Integration test verifies end-to-end hook execution
- [x] Manual testing confirms notifications work in Telegram and Redis sessions
- [x] Documentation updated with hook registration instructions

## Open Questions

1. **Which Claude Code hook event should trigger this?**

   - Likely `UserPromptSubmit` but need to verify with user
   - May need custom event for "agent waiting for input"

2. **Should we rate-limit notifications?**

   - If Claude becomes ready multiple times quickly, limit to 1 notification per minute?
   - Initial implementation: no rate limiting (KISS)

3. **Should hook support --notify flag like reference implementation?**

   - Reference hook has TTS toggle via --notify flag
   - Our hook is UI-only, so probably not needed
   - Initial implementation: always send notification (KISS)

4. **Error handling when AdapterClient fails?**

   - If notification fails, should we retry or fail silently?
   - Initial implementation: log error and exit gracefully (best-effort)

5. **Inactivity timer reset vs pause?**
   - Should notification_sent flag reset timer to 0 or pause it entirely?
   - Initial implementation: reset to 0 when output changes (simplest)

## References

- **Reference Hook**: `/Users/Morriz/.claude/hooks/notification.py`

  - TTS integration (not needed for our use case)
  - Hook structure and stdin/stdout protocol
  - Message randomization pattern

- **TeleClaude Architecture**: `docs/architecture.md`

  - Module-level Singleton pattern (db)
  - AdapterClient as central hub
  - Observer pattern for events

- **Existing UX State**: `teleclaude/core/models.py`

  - JSON blob structure in `ux_state` column
  - No migration needed for new fields

- **Polling Coordinator**: `teleclaude/core/polling_coordinator.py`

  - IdleDetected event handling (line 201)
  - UX state management for notifications

- **Database Helpers**: `teleclaude/core/db.py`
  - `update_ux_state()` pattern for JSON blob updates
  - Transaction handling for async updates
