# Integration Test Coverage Analysis

**Generated:** 2025-01-08

This document maps integration tests to use cases defined in `docs/use_cases.md`.

---

## Coverage Matrix

| Use Case                                               | Test File                      | Test Name                                      | Status                   |
| ------------------------------------------------------ | ------------------------------ | ---------------------------------------------- | ------------------------ |
| **UC-H1: Create New Tmux Session**                     | test_core.py                   | test_session_manager_crud                      | ✅ Partial (DB only)     |
| **UC-H1: Create New Tmux Session**                     | test_full_flow.py              | test_message_execution_and_output_polling      | ✅ Full                  |
| **UC-H2: Execute Tmux Command (Human Mode)**           | test_full_flow.py              | test_command_execution_via_terminal            | ✅ Full                  |
| **UC-H2: Execute Tmux Command (Human Mode)**           | test_process_exit_detection.py | test_process_detection_uses_output_message_id  | ✅ Full                  |
| **UC-H3: Long-Running Command with Idle Notification** | -                              | -                                              | ❌ Missing               |
| **UC-H4: Download Large Output**                       | -                              | -                                              | ❌ Missing               |
| **UC-H5: Send Voice Command**                          | test_voice_status_append.py    | test_append_status_to_existing_output          | ✅ Partial (status only) |
| **UC-A1: AI Initiates Cross-Computer Session**         | test_mcp_tools.py              | test_teleclaude_start_session_success          | ✅ Full                  |
| **UC-A1: AI Initiates Cross-Computer Session**         | test_mcp_redis.py              | test_teleclaude_start_session                  | ✅ Full                  |
| **UC-A2: AI Executes Remote Command (AI Mode)**        | test_full_flow.py              | test_multi_computer_mcp_command_execution      | ✅ Full                  |
| **UC-A2: AI Executes Remote Command (AI Mode)**        | test_mcp_tools.py              | test_teleclaude_send_success                   | ✅ Full                  |
| **UC-A2: AI Executes Remote Command (AI Mode)**        | test_concurrent_ai_sessions.py | test_concurrent_sessions_dont_interfere        | ✅ Stress                |
| **UC-A2: AI Executes Remote Command (AI Mode)**        | test_concurrent_ai_sessions.py | test_three_computer_chain                      | ✅ Multi-hop             |
| **UC-A3: AI Polls Output Stream**                      | test_concurrent_ai_sessions.py | test_concurrent_streaming_sessions             | ✅ Full                  |
| **UC-S1: List Active Sessions**                        | test_mcp_tools.py              | test_teleclaude_list_sessions                  | ✅ Full                  |
| **UC-S1: List Active Sessions**                        | test_mcp_redis.py              | test_teleclaude_list_sessions                  | ✅ Full                  |
| **UC-S2: Close Session**                               | -                              | -                                              | ❌ Missing               |
| **UC-S3: Session Recovery After Daemon Restart**       | test_process_exit_detection.py | test_process_detection_survives_daemon_restart | ✅ Full                  |
| **UC-V1: Voice Command Confirmation Flow**             | -                              | -                                              | ❌ Missing               |
| **UC-V2: Voice Transcription Error Handling**          | -                              | -                                              | ❌ Missing               |
| **UC-M1: Telegram User with Redis Observer**           | -                              | -                                              | ❌ Missing               |
| **UC-M2: Multiple UI Observers (Future)**              | -                              | -                                              | ❌ N/A (future)          |

---

## Coverage Summary

| Category                    | Covered | Partial | Missing | Total  |
| --------------------------- | ------- | ------- | ------- | ------ |
| Human-Interactive (UC-H\*)  | 2       | 2       | 1       | 5      |
| AI-to-AI (UC-A\*)           | 3       | 0       | 0       | 3      |
| Session Management (UC-S\*) | 2       | 0       | 1       | 3      |
| Voice (UC-V\*)              | 0       | 1       | 1       | 2      |
| Multi-Adapter (UC-M\*)      | 0       | 0       | 1       | 2      |
| **Total**                   | **7**   | **3**   | **4**   | **15** |

**Coverage: 47% Full, 20% Partial, 27% Missing**

---

## Missing Test Cases (Priority Order)

### High Priority

1. **UC-H3: Long-Running Command with Idle Notification**
   - File: `test_idle_notification.py`
   - Tests idle detection, notification send, notification cleanup
   - Critical UX feature

2. **UC-S2: Close Session**
   - File: `test_session_lifecycle.py`
   - Tests `/exit` command, tmux cleanup, file cleanup, DB update
   - Core lifecycle feature

3. **UC-M1: Telegram User with Redis Observer**
   - File: `test_multi_adapter_broadcasting.py`
   - Tests origin vs observer routing, `has_ui` flag filtering
   - Core architecture validation

### Medium Priority

4. **UC-H4: Download Large Output**
   - File: `test_large_output_download.py`
   - Tests truncation, download button, temp file cleanup
   - Important UX feature

5. **UC-V1: Voice Command Confirmation Flow**
   - File: `test_voice_full_flow.py`
   - Tests transcription → confirmation → execution
   - Complete voice feature validation

### Low Priority

6. **UC-V2: Voice Transcription Error Handling**
   - File: `test_voice_error_handling.py`
   - Tests Whisper failure handling
   - Edge case coverage

---

## Tests to Build

### 1. test_idle_notification.py

```python
"""Integration test for idle notification during long-running commands."""

@pytest.mark.integration
async def test_idle_notification_sent_after_60_seconds():
    """Test idle notification appears after 60s of no output."""
    # Setup: Create session, start command that produces no output
    # Wait 61 seconds
    # Assert: idle notification sent via adapter_client.send_message()
    # Assert: notification_id stored in ux_state

@pytest.mark.integration
async def test_idle_notification_deleted_when_output_resumes():
    """Test idle notification deleted when output changes."""
    # Setup: Trigger idle notification
    # Send new output
    # Assert: adapter_client.delete_message() called with notification_id
    # Assert: notification_id cleared from ux_state
```

### 2. test_session_lifecycle.py

```python
"""Integration test for complete session lifecycle."""

@pytest.mark.integration
async def test_close_session_full_cleanup():
    """Test /exit command performs complete cleanup."""
    # Setup: Create session, run command
    # Execute: Send /exit command
    # Assert: tmux session killed
    # Assert: output file deleted
    # Assert: session deleted from DB
    # Assert: polling stopped

@pytest.mark.integration
async def test_close_session_with_active_polling():
    """Test closing session while command is running."""
    # Setup: Start long-running command
    # Execute: Send /exit while polling active
    # Assert: Polling stopped gracefully
    # Assert: Cleanup completed
```

### 3. test_multi_adapter_broadcasting.py

```python
"""Integration test for multi-adapter broadcasting."""

@pytest.mark.integration
async def test_last_input_origin_receives_output():
    """Test output sent to origin adapter (CRITICAL)."""
    # Setup: Create session with last_input_origin="telegram"
    # Execute: Send command
    # Assert: Output sent to TelegramAdapter
    # Assert: send_message() called on origin adapter

@pytest.mark.integration
async def test_redis_observer_skipped_no_ui():
    """Test RedisTransport (has_ui=False) skipped for broadcasts."""
    # Setup: Session with telegram origin, redis as observer
    # Execute: Send command
    # Assert: Output sent to telegram (origin)
    # Assert: Redis send_message() NOT called (has_ui=False)
```

### 4. test_large_output_download.py

```python
"""Integration test for large output download feature."""

@pytest.mark.integration
async def test_output_truncated_with_download_button():
    """Test output > 3800 chars shows download button."""
    # Setup: Command that produces > 3800 chars output
    # Execute: Command completes
    # Assert: Message truncated to last 3400 chars
    # Assert: Download button present in message metadata

@pytest.mark.integration
async def test_download_button_creates_temp_file():
    """Test clicking download button sends full output."""
    # Setup: Large output with download button
    # Execute: Simulate button click
    # Assert: Temp file created with full output
    # Assert: send_document() called
    # Assert: Temp file deleted after send
```

### 5. test_voice_full_flow.py

```python
"""Integration test for voice command complete flow."""

@pytest.mark.integration
async def test_voice_transcription_confirmation_execution():
    """Test complete voice flow: upload → transcribe → confirm → execute."""
    # Setup: Mock Whisper transcription
    # Execute: Send voice message
    # Assert: Transcription status shown
    # Assert: Confirmation buttons shown
    # Execute: Click [Execute]
    # Assert: Command executed in terminal
    # Assert: Output shown

@pytest.mark.integration
async def test_voice_confirmation_cancel():
    """Test canceling voice command after transcription."""
    # Execute: Send voice, transcribe, click [Cancel]
    # Assert: Command NOT executed
    # Assert: Cancellation message shown
```

---

## Existing Tests - Enhancement Needed

### test_voice_status_append.py

**Current:** Tests status message appending to output message
**Missing:** Full voice flow (transcription → confirmation → execution)
**Action:** Extract to separate test_voice_full_flow.py, keep append-specific tests

---

## Test Execution Status

Run integration tests:

```bash
.venv/bin/pytest tests/integration/ -v
```

Current status: **Need to build 6 new test files**

---

**End of Coverage Analysis**
