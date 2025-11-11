# TeleClaude Integration Test Coverage

This document maps all critical user pathways to integration tests, identifying what's tested and what's missing.

## Test Organization

- **Unit tests** (`tests/unit/`): Test individual components in isolation
- **Integration tests** (`tests/integration/`): Test complete workflows end-to-end

## Critical User Pathways

### 1. Human User → Telegram → Terminal (Interactive Mode)

**Flow**: User sends command via Telegram → Daemon executes → Output polled → Sent back to Telegram

**Current Coverage**:
- ✅ `test_full_flow::test_message_execution_and_output_polling` - Command execution + output polling
- ✅ `test_full_flow::test_command_execution_via_terminal` - Direct terminal execution
- ✅ `test_process_exit_detection::test_process_detection_uses_output_message_id` - Exit detection
- ✅ `test_process_exit_detection::test_process_detection_survives_daemon_restart` - Persistence
- ✅ `test_polling_restart::test_polling_restarts_after_process_exits` - Polling lifecycle
- ✅ `test_session_lifecycle::test_close_session_full_cleanup` - Session cleanup

**Missing Tests**:
- ❌ **Notification Chain**: Poller detects idle → MCP send_notification called → Notification sent to Telegram
- ❌ **Notification Chain**: Poller detects completion → MCP send_notification called → Completion message sent
- ❌ **Error handling**: Command fails → Error captured → Error message sent to user

### 2. AI → MCP → Remote Computer (Cross-Computer Orchestration)

**Flow**: AI calls MCP tool → Redis transport → Remote computer executes → Output streamed back

**Current Coverage**:
- ✅ `test_full_flow::test_multi_computer_mcp_command_execution` - Full AI-to-AI flow with real tmux
- ✅ `test_mcp_tools::test_teleclaude_list_computers` - List computers via MCP
- ✅ `test_mcp_tools::test_teleclaude_start_session_success` - Start remote session
- ✅ `test_mcp_tools::test_teleclaude_send_success` - Send command to remote
- ✅ `test_redis_heartbeat::test_heartbeat_includes_role` - Heartbeat mechanism
- ✅ `test_redis_heartbeat::test_discover_peers_new_fields` - Peer discovery

**Missing Tests**:
- ❌ **Interest Window Pattern**: MCP send_message → 15s stream → detach → poll status later
- ❌ **Error propagation**: Remote command fails → Error returned to AI caller
- ❌ **Timeout handling**: Remote command times out → Timeout reported to AI

### 3. File Upload Workflow

**Flow**: User uploads file → Daemon saves → Path sent to terminal (Claude Code or other process)

**Current Coverage**:
- ✅ `test_file_upload::test_file_upload_with_claude_code` - Upload with @ prefix for Claude
- ✅ `test_file_upload::test_file_upload_without_claude_code` - Upload with plain path
- ✅ `test_file_upload::test_rejection_when_no_process_active` - Upload rejected when idle
- ✅ `test_file_upload::test_session_cleanup_deletes_files` - File cleanup on session end

**Missing Tests**:
- ❌ **Large file handling**: File >10MB upload → Chunked processing
- ❌ **Voice file handling**: Voice message → Transcription → Text sent to terminal

### 4. Multi-Adapter Broadcasting

**Flow**: Output generated → Sent to origin adapter → Broadcast to observers (Slack, Redis, etc.)

**Current Coverage**:
- ✅ `test_multi_adapter_broadcasting::test_origin_adapter_receives_output` - Origin receives (critical)
- ✅ `test_multi_adapter_broadcasting::test_redis_observer_skipped_no_ui` - Redis (has_ui=False) skipped
- ✅ `test_multi_adapter_broadcasting::test_ui_observer_receives_broadcasts` - UI observers receive
- ✅ `test_multi_adapter_broadcasting::test_observer_failure_does_not_affect_origin` - Best-effort observers
- ✅ `test_multi_adapter_broadcasting::test_origin_failure_raises_exception` - Origin failure critical

**Missing Tests**:
- ❌ **Multiple UI observers**: Telegram + Slack both receive broadcasts
- ❌ **Observer reconnection**: Redis disconnects → Reconnects → Resumes receiving

### 5. Idle Notification System

**Flow**: Poller detects idle (60s no output) → Ephemeral notification sent → Auto-deleted on next output

**Current Coverage**:
- ✅ `test_idle_notification::test_idle_notification_stored_in_ux_state` - State persistence
- ✅ `test_idle_notification::test_idle_notification_cleared_when_output_resumes` - Auto-cleanup
- ✅ `test_idle_notification::test_idle_notification_persists_across_restarts` - Survives restart
- ✅ `test_idle_notification::test_has_idle_notification_check` - Query utility

**Missing Tests**:
- ❌ **Idle notification sent via MCP**: Poller triggers → MCP send_notification → Message appears
- ❌ **Notification flag prevents duplicate**: notification_sent flag set → Skip sending again

### 6. Voice Status Append (Real-time Status)

**Flow**: Long-running process active → Voice transcription status appended to output message

**Current Coverage**:
- ⚠️ `test_voice_status_append::test_append_status_to_existing_output` - Status appends to output
- ⚠️ `test_voice_status_append::test_send_new_message_when_no_active_polling` - New message when idle
- ⚠️ `test_voice_status_append::test_append_without_message_id_sends_new` - Fallback behavior
- ⚠️ `test_voice_status_append::test_append_handles_stale_message_id` - Stale message handling

**Status**: Tests exist but currently failing (needs investigation)

### 7. Session Lifecycle Management

**Flow**: Create session → Execute commands → Close → Reopen → Delete

**Current Coverage**:
- ✅ `test_session_lifecycle::test_close_session_full_cleanup` - Close cleans up resources
- ✅ `test_session_lifecycle::test_close_session_with_active_polling` - Close stops polling
- ✅ `test_session_lifecycle::test_close_session_idempotent` - Multiple closes safe
- ✅ `test_session_lifecycle::test_close_session_does_not_delete_from_db` - Close vs delete
- ✅ `test_core::test_session_manager_crud` - Basic CRUD operations
- ✅ `test_core::test_session_manager_with_metadata` - Metadata handling

**Missing Tests**:
- ❌ **Reopen workflow**: Session closed → User reopens → tmux session recreated at last working_directory
- ❌ **Channel status updates**: Session closed → Telegram topic shows "🔒 Closed" → Reopened → Shows "active"

---

## Priority Test Gaps (High Impact)

### P0: Must Have Before Deployment

1. **✅ COMPLETED: Multi-adapter broadcasting** (origin + observers)
   - Tests exist and passing

2. **❌ MISSING: Notification chain end-to-end**
   ```python
   # tests/integration/test_notification_chain.py

   async def test_idle_notification_sent_via_mcp():
       """Test: Poller detects idle → MCP notification → Telegram message."""
       # 1. Start session with active command
       # 2. Let poller detect idle (mock 60s wait)
       # 3. Verify MCP send_notification called
       # 4. Verify Telegram receives message

   async def test_completion_notification_sent_via_mcp():
       """Test: Command completes → MCP notification → Telegram message."""
       # 1. Execute command
       # 2. Wait for exit code detection
       # 3. Verify MCP send_notification called with completion message
       # 4. Verify Telegram receives message
   ```

3. **❌ MISSING: MCP interest window pattern**
   ```python
   # tests/integration/test_mcp_interest_window.py

   async def test_send_message_interest_window():
       """Test: AI sends command → Stream 15s → Detach → Poll status later."""
       # 1. AI calls teleclaude__send_message
       # 2. Verify initial output streamed for 15s
       # 3. Verify detaches after interest window
       # 4. AI calls teleclaude__get_session_status
       # 5. Verify accumulated output since last check
   ```

### P1: Should Have (Improves Confidence)

4. **❌ MISSING: Session reopen workflow**
   ```python
   # tests/integration/test_session_reopen.py

   async def test_reopen_creates_tmux_at_saved_directory():
       """Test: Closed session → Reopen → tmux created at last working_directory."""
       # Already exists in test_daemon.py but should be in integration tests
   ```

5. **❌ MISSING: Channel status lifecycle**
   ```python
   # tests/integration/test_channel_status.py

   async def test_channel_status_updates_on_close_reopen():
       """Test: Session closed → Topic shows closed → Reopened → Shows active."""
       # Test set_channel_status integration
   ```

6. **❌ MISSING: Error handling pathways**
   ```python
   # tests/integration/test_error_handling.py

   async def test_command_failure_reported_to_user():
       """Test: Command fails (exit 1) → Error captured → Sent to Telegram."""

   async def test_remote_command_timeout_reported():
       """Test: Remote command times out → Timeout message to AI caller."""
   ```

### P2: Nice to Have (Edge Cases)

7. **❌ MISSING: Large file handling**
8. **❌ MISSING: Voice transcription workflow**
9. **❌ MISSING: Multiple UI observers**
10. **❌ MISSING: Adapter reconnection**

---

## Test Implementation Checklist

When implementing missing tests, ensure:

1. **Use proper fixtures**: `daemon_with_mocked_telegram` from `conftest.py`
2. **Test actual pathways**: Don't mock the chain, test it end-to-end
3. **Verify side effects**: Check database state, message counts, file cleanup
4. **Use real tmux**: Integration tests should use actual `terminal_bridge` operations
5. **Clean up resources**: Use `try/finally` to clean up tmux sessions, files, etc.
6. **Timeout appropriately**: Use `@pytest.mark.timeout(15)` for integration tests
7. **Document intent**: Clear docstring explaining what pathway is being tested

---

## Test File Organization

### Current Structure
```
tests/
├── unit/                      # Component-level tests
│   ├── test_adapter_client.py
│   ├── test_db.py
│   ├── test_output_poller.py
│   └── ...
├── integration/               # End-to-end workflow tests
│   ├── test_core.py           # Basic CRUD + terminal ops
│   ├── test_full_flow.py      # Human user workflows
│   ├── test_mcp_tools.py      # AI workflows
│   ├── test_multi_adapter_broadcasting.py
│   ├── test_idle_notification.py
│   ├── test_session_lifecycle.py
│   └── test_file_upload.py
└── README.md                  # This file

### Proposed Additions
tests/integration/
├── test_notification_chain.py     # NEW: Idle/completion notifications
├── test_mcp_interest_window.py    # NEW: Interest window pattern
├── test_channel_status.py         # NEW: Channel lifecycle
├── test_error_handling.py         # NEW: Error propagation
└── test_voice_transcription.py    # NEW: Voice workflow
```

---

## Running Tests

```bash
# Run all tests
make test

# Run only integration tests
make test-e2e

# Run only unit tests
make test-unit

# Run specific test file
pytest tests/integration/test_notification_chain.py -v

# Run specific test
pytest tests/integration/test_notification_chain.py::test_idle_notification_sent_via_mcp -v
```

---

## Key Insights

1. **Poller detects idle, not Claude Code** - Clarified architecture
2. **Hooks are external to daemon** - Claude Code calls hooks, not daemon
3. **Test the chain FROM the hook** - Simulate MCP call, verify adapter receives
4. **Output polling ≠ Notifications** - Two separate concerns, separate tests
5. **Integration tests touch real systems** - Use real tmux, real files, mock only adapters

---

**Last Updated**: 2025-11-11
**Next Review**: After implementing P0 missing tests
