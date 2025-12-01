# Session Object Refactoring Progress

## Completed

### 1. BaseAdapter Infrastructure ✅
- Added `_get_session(session_id)` helper - validates and returns Session, raises if not found
- Added `send_error_feedback(session_id, error_message)` method (default no-op)
- Added `@with_error_feedback` decorator - catches exceptions and calls send_error_feedback
- Updated BaseAdapter interface signatures:
  - `create_channel(session, title, metadata)`
  - `update_channel_title(session, title)`
  - `close_channel(session)`
  - `reopen_channel(session)`
  - `delete_channel(session)`
  - `poll_output_stream(session, timeout)`

### 2. UiAdapter ✅
- Implemented `send_error_feedback` - sends ❌ feedback message to user

### 3. RedisAdapter ✅
- Implemented `send_error_feedback` - publishes error envelope to output stream with `type: error` field

## Issues Found

### AdapterClient.update_channel_title is BROKEN
**File:** `teleclaude/core/adapter_client.py:415`
**Problem:** Calls `self.update_channel_title(channel_id, title)` where `channel_id` is undefined
**Fix needed:** Should broadcast to ALL adapters (facade/multiplexer pattern), not just origin

### TelegramAdapter.update_channel_title signature mismatch
**Current:** `async def update_channel_title(self, channel_id: str, title: str)`
**Expected:** `async def update_channel_title(self, session: Session, title: str)`
**Problem:** Takes channel_id directly instead of session object

## Next Steps

### Phase 1: Complete Adapter Refactoring
1. **TelegramAdapter** - Update channel methods + helpers:
   - `create_channel(session, title, metadata)` - already doesn't use session_id, just change signature
   - `update_channel_title(session, title)` - fix signature, extract topic_id from session.adapter_metadata.telegram
   - `close_channel(session)` - remove db.get_session lookup
   - `reopen_channel(session)` - remove db.get_session lookup
   - `delete_channel(session)` - remove db.get_session lookup
   - `_handle_telegram_error(session, error, operation)`
   - `_edit_message_with_retry(session, ctx)`
   - `_post_handle_user_input(session, message_id)`

2. **RedisAdapter** - Update channel methods + helpers:
   - `create_channel(session, title, metadata)` - extract output_stream from session
   - `update_channel_title(session, title)` - no-op, just change signature
   - `close_channel(session)` - no-op, just change signature
   - `reopen_channel(session)` - no-op, just change signature
   - `delete_channel(session)` - extract stream info from session
   - `poll_output_stream(session, timeout)` - extract output_stream from session
   - `_start_output_stream_listener(session)`
   - `_poll_output_stream_for_messages(session)`
   - `is_session_observed(session)`

3. **AdapterClient** - Update and FIX:
   - `update_channel_title(session, title)` - FIX broken implementation
   - `delete_channel(session)`

4. **Daemon** - Update methods:
   - `_get_output_file_path(session)`
   - `handle_message(session, text, context)`
   - `_start_tmux_capture(session, tmux_session_name, marker_id)`

5. **Other Core**:
   - `SessionCleanup.cleanup_stale_session(session, adapter_client)`
   - `VoiceMessageHandler.handle_voice_message(session, ...)`
   - `FileHandler.handle_file` - add boundary validation at entry
   - `UiAdapter._get_output_file_path(session)`

### Phase 2: Update All Callers
- Search for all places calling these methods with session_id
- Add boundary validation where needed: `session = await adapter._get_session(session_id)`
- Pass Session objects to inner methods

### Phase 3: Apply Error Feedback Decorator
- TelegramAdapter boundary handlers
- RedisAdapter boundary handlers
- CommandHandlers methods
- FileHandler.handle_file
- VoiceMessageHandler.handle_voice_message

### Phase 4: Test & Restart
- Run all tests
- Fix failures
- Restart daemon
- Verify system works

## Architecture Notes

**Boundary Layer** (validates once, passes Session inward):
- MCP tools
- Telegram message handlers
- Redis message handlers
- File upload handlers

**Core Layer** (only uses Session, never session_id):
- All adapter methods
- AdapterClient facade
- Daemon handlers
- Command handlers
- Session cleanup

**Storage Layer** (keeps session_id):
- Db methods (they ARE the lookup mechanism)
- Event dataclasses (just data carriers)
- Pure utilities (stateless functions)
- Logging functions (no business logic)
