# Claude Code Notification Hook Integration - Task Breakdown

> **PRD**: prds/notifications.md
> **Status**: 🚧 In Progress
> **Started**: 2025-01-11

## Implementation Tasks

### Phase 1: Setup & Directory Structure

- [ ] Create `teleclaude/hooks/` directory if it doesn't exist
- [ ] Verify existing dependencies (python-dotenv, pyyaml, aiosqlite) are available

### Phase 2: Core Implementation

- [ ] **Create notification hook script** (`teleclaude/hooks/notification.py`)
  - Add shebang: `#!/usr/bin/env -S uv run --script`
  - Add script dependencies block for uv
  - Implement stdin JSON reading for session_id
  - Create 15 randomized notification message templates
  - Implement random message selection logic
  - Bootstrap AdapterClient from config (similar to daemon.py pattern)
  - Send notification via adapter_client.send_message()
  - Update UX state to set notification_sent flag
  - Add proper error handling and logging
  - Exit cleanly with code 0

- [ ] **Add UX state helper functions** (`teleclaude/core/db.py`)
  - Add `set_notification_flag(session_id: str, value: bool)` function
  - Add `clear_notification_flag(session_id: str)` function
  - Add `get_notification_flag(session_id: str) -> bool` function
  - Ensure proper JSON blob handling for ux_state

- [ ] **Update polling coordinator** (`teleclaude/core/polling_coordinator.py`)
  - Import notification flag helper functions
  - Check `notification_sent` flag when starting inactivity timer
  - Clear `notification_sent` flag when OutputChanged event occurs (activity detected)
  - Add logic to skip/reset inactivity timer when notification_sent=True
  - Add logging for notification flag state changes

### Phase 3: Testing

- [ ] **Write unit tests for UX state helpers** (`tests/unit/test_db.py`)
  - Test `set_notification_flag()` updates ux_state JSON correctly
  - Test `clear_notification_flag()` removes flag from ux_state
  - Test `get_notification_flag()` returns correct boolean
  - Test flag persistence across multiple updates
  - Test behavior with missing/null ux_state

- [ ] **Write unit tests for message randomization** (`tests/unit/test_notification_hook.py`)
  - Test all 15 messages can be selected
  - Test random.choice() is called correctly
  - Mock AdapterClient and verify send_message is called
  - Test JSON stdin parsing
  - Test error handling for invalid JSON

- [ ] **Write unit tests for polling coordinator changes** (`tests/unit/test_polling_coordinator.py`)
  - Test inactivity timer respects notification_sent flag
  - Test flag is cleared on OutputChanged event
  - Test IdleDetected events are handled correctly with flag set
  - Test flag persistence across polling cycles

- [ ] **Write integration test for hook execution** (`tests/integration/test_notification_hook.py`)
  - Create test session in database
  - Invoke hook script with test JSON via stdin
  - Verify notification message sent to session
  - Verify ux_state updated with notification_sent=True
  - Test end-to-end flow with real AdapterClient

### Phase 4: Documentation

- [ ] **Update CLAUDE.md** with hook registration instructions
  - Add section on notification hook setup
  - Document hook registration in Claude Code settings
  - Provide example hook configuration
  - Document notification_sent flag behavior

- [ ] **Update README.md** with notification feature
  - Add notification hook to features list
  - Document user setup instructions
  - Add troubleshooting section for hook issues

- [ ] **Add docstrings and comments**
  - Ensure notification.py has comprehensive module docstring
  - Add comments explaining AdapterClient bootstrap pattern
  - Document notification flag coordination in polling_coordinator.py

### Phase 5: Code Quality

- [ ] Run `make format` to format all new/modified code
- [ ] Run `make lint` to check for linting issues
  - Fix any pylint warnings
  - Fix any mypy type errors
- [ ] Run `make test-unit` to verify unit tests pass
- [ ] Run `make test-e2e` to verify integration tests pass
- [ ] Run `make test` to verify full test suite passes

### Phase 6: Manual Testing

- [ ] **Test hook script standalone**
  - Run hook with test JSON: `echo '{"session_id":"test-123"}' | teleclaude/hooks/notification.py`
  - Verify message appears in test session
  - Verify UX state updated in database

- [ ] **Test with real Claude Code session**
  - Register hook in `.claude/hooks/` or project hooks
  - Start TeleClaude session via Telegram
  - Trigger Claude Code task
  - Verify notification appears when Claude becomes ready
  - Verify no duplicate idle notifications

- [ ] **Test inactivity timer coordination**
  - Send notification via hook
  - Wait 60+ seconds with no output
  - Verify idle notification doesn't fire (flag is set)
  - Send output change
  - Verify idle notification resumes (flag cleared)

- [ ] **Test across adapters**
  - Test notification in Telegram session
  - Test notification in Redis session (if applicable)
  - Verify broadcast to all UI adapters works

### Phase 7: Deployment

- [ ] Test locally with `make restart && make status`
- [ ] Verify daemon health after changes
- [ ] Monitor logs for any errors: `tail -f /var/log/teleclaude.log`
- [ ] Create commit with `/commit`
- [ ] Deploy to all machines with MCP tool or manual SSH
- [ ] Verify deployment on RasPi: `ssh morriz@raspberrypi.local "cd /home/morriz/apps/TeleClaude && make status"`
- [ ] Verify deployment on RasPi4: `ssh morriz@raspi4.local "cd /home/morriz/apps/TeleClaude && make status"`

## Notes

### Implementation Decisions

- **Hook location**: Created in `teleclaude/hooks/` instead of project root to keep code organized
- **UX state field**: Using `notification_sent` boolean flag in existing ux_state JSON blob (no schema migration)
- **Inactivity timer logic**: Reset flag on OutputChanged, pause timer when flag=True
- **Message templates**: 15 friendly, casual messages with variety

### Open Questions Resolved

1. **Hook event trigger**: User will configure in their Claude Code settings (likely UserPromptSubmit)
2. **Rate limiting**: Not implemented in v1 (KISS principle)
3. **Error handling**: Best-effort notification, log errors and exit gracefully
4. **Timer behavior**: Reset to 0 when output changes (simplest approach)

### Blockers

- None currently

## Completion Checklist

Before marking this work complete:

- [ ] All tests pass (`make test`)
- [ ] Code formatted and linted (`make format && make lint`)
- [ ] Changes deployed to all machines
- [ ] Success criteria from PRD verified:
  - [ ] Hook sends randomized messages
  - [ ] AdapterClient bootstrapped correctly
  - [ ] Inactivity timer coordination works
  - [ ] UX state persists across restarts
  - [ ] >90% test coverage for new code
  - [ ] Integration test passes
  - [ ] Manual testing in Telegram/Redis works
  - [ ] Documentation updated
- [ ] Roadmap item marked as complete (`[x]`)

---

**Remember**: Use TodoWrite tool to track progress on these tasks!
