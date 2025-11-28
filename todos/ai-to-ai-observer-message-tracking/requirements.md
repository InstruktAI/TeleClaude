# AI-to-AI Observer Message Tracking

> **Created**: 2025-11-28
> **Status**: 📝 Requirements

## Problem Statement

When an AI session is initiated from MozBook to RasPi4 (AI-to-AI communication), the RasPi4 TelegramAdapter acts as an "observer" - it receives real-time output updates to display in Telegram. However, we recently implemented per-adapter message tracking (commit 7e9e2c7) that should allow observer adapters to edit a SINGLE message instead of creating multiple new messages for each output chunk.

**Pain Points**:
- Code deployed but not verified in production
- Unknown if `adapter_metadata[adapter_type]["output_message_id"]` is being correctly stored and retrieved
- Telegram message spam (multiple messages vs one edited message) creates poor UX
- No test coverage for observer message tracking in live AI-to-AI sessions

**Why Now**: The observer message tracking feature was just deployed to production. We need to verify it works as designed before building additional features on top of this foundation.

## Goals

**Primary Goals**:
- Verify observer message tracking works correctly in live AI-to-AI sessions
- Fix any bugs preventing observers from editing single messages
- Document the verified behavior for future reference

**Secondary Goals**:
- Add logging to make debugging easier in production
- Consider integration tests for observer message tracking

## Non-Goals

- Implementing new features (stay focused on verification/fixes only)
- Changing the architecture of observer pattern
- Optimizing performance (unless blocking verification)
- Adding UI improvements beyond message editing

## User Stories / Use Cases

### Story 1: Multi-Computer AI Collaboration

As a **user running AI sessions across multiple computers**, I want observer adapters (like Telegram on RasPi4) to edit a single message with streaming updates so that I can follow the session progress without message spam.

**Acceptance Criteria**:
- [ ] When MozBook initiates AI-to-AI session on RasPi4, RasPi4 Telegram shows ONE message
- [ ] The single message updates continuously with new output (not multiple messages)
- [ ] Message edits reflect latest output with proper status line formatting

### Story 2: Developer Debugging Observer Issues

As a **developer debugging AI-to-AI sessions**, I want clear logs showing when message_id is stored/retrieved so that I can diagnose observer tracking issues.

**Acceptance Criteria**:
- [ ] Logs show when `adapter_metadata[adapter_type]["output_message_id"]` is written
- [ ] Logs show when message_id is retrieved for editing
- [ ] Logs indicate which adapter (telegram/redis) is performing the action

## Technical Constraints

- Must work with existing `UiAdapter.send_output_update()` architecture
- Must use `adapter_metadata[adapter_type]` storage pattern (already implemented)
- Must support multiple observer adapters simultaneously (Telegram on different computers)
- Cannot break existing origin adapter behavior (sessions initiated from Telegram directly)
- Must work with Redis output stream distribution (already implemented)

## Success Criteria

How will we know this is successful?

- [ ] **Live Verification**: Start AI-to-AI session MozBook → RasPi4, confirm RasPi4 Telegram edits ONE message (not multiple)
- [ ] **Database Verification**: Confirm `adapter_metadata.telegram.output_message_id` is stored in remote session
- [ ] **Log Verification**: Logs show message_id storage and retrieval events
- [ ] **Regression Check**: Existing Telegram sessions (non-observer) still work correctly
- [ ] **Code Quality**: All tests pass (`make test && make lint`)

## Open Questions

- ❓ Is the `_get_adapter_key()` method correctly identifying adapter type via class name?
- ❓ Is `send_output_update()` being called for observer adapters during AI-to-AI sessions?
- ❓ Is the Redis output stream correctly distributing updates to observer adapters?
- ❓ Does the database update correctly when storing message_id in `adapter_metadata`?

## References

- **Recent commit**: 7e9e2c7 - feat(adapters): per-adapter message tracking for observers
- **Architecture docs**: docs/architecture.md (Observer Pattern section)
- **Code locations**:
  - `teleclaude/adapters/ui_adapter.py` - `_get_adapter_key()`, `send_output_update()`
  - `teleclaude/adapters/telegram_adapter.py` - Observer adapter implementation
  - `teleclaude/adapters/redis_adapter.py` - AI-to-AI session creation and output streaming
  - `teleclaude/core/polling_coordinator.py` - Output distribution to adapters
