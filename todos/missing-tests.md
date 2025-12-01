# Missing Unit Test Coverage

**Current Coverage: 17/28 modules (60%)**

**Status:** Test stubs created (79 skipped tests), ready for implementation

**Test Files Created:**
- `tests/unit/test_redis_adapter.py` (6 tests)
- `tests/unit/test_command_handlers.py` (16 tests)
- `tests/unit/test_mcp_server.py` (9 tests)
- `tests/unit/test_voice_message_handler.py` (11 tests)
- `tests/unit/test_session_cleanup.py` (9 tests)
- `tests/unit/test_session_utils.py` (6 tests)
- `tests/unit/test_ux_state.py` (10 tests)
- `tests/unit/test_events.py` (7 tests)
- `tests/unit/test_session_lifecycle_logger.py` (6 tests)

**Files NOT Created (No Custom Logic):**
- `metadata.py` - Pure Pydantic models
- `logging_config.py` - Configuration only

---

## High Priority (Large, Complex Business Logic)

### 1. `adapters/redis_adapter.py` (1244 lines) ✅ STUBS CREATED (6 tests)

**Current Coverage:** Integration tests only (test_multi_adapter_broadcasting.py, test_redis_heartbeat.py)

**Missing Unit Tests:**
- [ ] Peer discovery logic (`discover_peers()`)
- [ ] Stream message parsing (`_parse_stream_message()`)
- [ ] Heartbeat formatting and sending
- [ ] Message stream operations (xadd, xread)
- [ ] Output stream operations
- [ ] Connection error handling
- [ ] Redis reconnection logic

**Complexity:** HIGH - distributed system coordination

---

### 2. `core/command_handlers.py` (1093 lines) ✅ STUBS CREATED (16 tests)

**Current Coverage:** Integration tests only (test_command_e2e.py, test_ai_to_ai_session_init_e2e.py)

**Missing Unit Tests:**
- [ ] `handle_new_session()` - session creation logic
- [ ] `handle_create_session()` - MCP session creation
- [ ] `handle_list_sessions()` - session listing and formatting
- [ ] `handle_get_session_data()` - session data retrieval
- [ ] `handle_list_projects()` - project listing
- [ ] `handle_cd()` - directory change validation
- [ ] `handle_kill()` - process termination
- [ ] `handle_cancel()` - Ctrl+C sending
- [ ] `handle_escape()` - ESC key sending
- [ ] `handle_ctrl()` - Ctrl key combinations
- [ ] `handle_rename()` - session renaming
- [ ] `handle_claude()` - Claude Code startup
- [ ] `handle_claude_resume()` - Claude Code resume
- [ ] `handle_message()` - message forwarding to process
- [ ] Error handling for invalid session states
- [ ] Edge cases (session not found, no active process, etc.)

**Complexity:** HIGH - central routing logic with many branches

---

### 3. `mcp_server.py` (1095 lines) ✅ STUBS CREATED (9 tests)

**Current Coverage:** Integration tests only (test_mcp_tools.py)

**Missing Unit Tests:**
- [ ] `teleclaude__list_computers()` - computer listing logic
- [ ] `teleclaude__list_sessions()` - session listing and formatting
- [ ] `teleclaude__start_session()` - session creation via MCP
- [ ] `teleclaude__send_message()` - message sending via MCP
- [ ] `teleclaude__send_notification()` - notification sending
- [ ] `teleclaude__send_file()` - file upload logic
- [ ] `teleclaude__get_session_data()` - session data formatting
- [ ] `teleclaude__download_session()` - transcript download
- [ ] Error handling (invalid session_id, file not found, etc.)
- [ ] Data formatting edge cases

**Complexity:** HIGH - external API with complex data transformations

---

## Medium Priority (Utility Functions, Edge Cases)

### 4. `core/voice_message_handler.py` (283 lines) ✅ STUBS CREATED (11 tests)

**Current Coverage:** None

**Missing Unit Tests:**
- [ ] `init_voice_handler()` - initialization logic
- [ ] `transcribe_voice()` - Whisper API integration
- [ ] `transcribe_voice_with_retry()` - retry logic (1 retry = 2 attempts total)
- [ ] `handle_voice()` - session validation before accepting voice
- [ ] Error handling (file not found, API failure, no active process)
- [ ] Temporary file cleanup
- [ ] Edge case: output message not ready yet

**Complexity:** MEDIUM - external API with retry logic

---

### 5. `core/session_cleanup.py` (113 lines) ✅ STUBS CREATED (9 tests)

**Current Coverage:** None

**Missing Unit Tests:**
- [ ] `cleanup_stale_session()` - single session cleanup logic
- [ ] `cleanup_all_stale_sessions()` - batch cleanup
- [ ] Stale detection (DB says active, tmux gone)
- [ ] Resource cleanup (DB, channel, output file)
- [ ] Error handling (channel deletion failure, file deletion failure)
- [ ] Edge case: session already closed
- [ ] Edge case: tmux session exists (healthy session)

**Complexity:** MEDIUM - orchestration with multiple cleanup steps

---

### 6. `core/session_utils.py` (68 lines) ✅ STUBS CREATED (6 tests)

**Current Coverage:** None

**Missing Unit Tests:**
- [ ] `ensure_unique_title()` - title collision handling
- [ ] `get_output_file_path()` - path generation
- [ ] Edge case: no existing sessions (first session)
- [ ] Edge case: title exists (counter appending)
- [ ] Edge case: multiple collisions (counter = 3, 4, 5, etc.)

**Complexity:** LOW - simple utility functions

---

### 7. `core/ux_state.py` (277 lines) ✅ STUBS CREATED (10 tests)

**Current Coverage:** None (used in many integration tests but never tested in isolation)

**Missing Unit Tests:**
- [ ] `SessionUXState.from_dict()` - deserialization
- [ ] `SessionUXState.to_dict()` - serialization
- [ ] `SystemUXState.from_dict()` - deserialization
- [ ] `SystemUXState.to_dict()` - serialization
- [ ] `get_session_ux_state()` - retrieval logic
- [ ] `get_system_ux_state()` - retrieval logic
- [ ] `update_session_ux_state()` - partial update merging
- [ ] `update_system_ux_state()` - partial update merging
- [ ] Edge case: missing fields in stored JSON
- [ ] Edge case: invalid JSON in database
- [ ] Sentinel value (`_UNSET`) handling

**Complexity:** MEDIUM - stateful data management with merging

---

## Low Priority (Simple/Declarative)

### 8. `core/events.py` (197 lines) ✅ STUBS CREATED (7 tests)

**Missing Unit Tests:**
- [ ] `parse_command_string()` - command parsing
- [ ] Edge cases: quoted arguments, empty string, no args
- [ ] Pydantic model validation (event contexts)

**Complexity:** LOW - mostly declarative types + simple parsing

---

### 9. `core/metadata.py` (35 lines) ⏸️ SKIPPED

**Reason:** Pure Pydantic model with no custom logic - only tests Pydantic itself

---

### 10. `core/session_lifecycle_logger.py` (126 lines) ✅ STUBS CREATED (6 tests)

**Missing Unit Tests:**
- [ ] `log_lifecycle_event()` - JSON writing
- [ ] Helper functions (log_session_created, log_polling_started, etc.)
- [ ] File creation and appending
- [ ] Error handling (disk full, permissions)

**Complexity:** LOW - simple file I/O

---

### 11. `logging_config.py` ⏸️ SKIPPED

**Reason:** Configuration only - no logic to test

---

## Summary

**Total Test Stubs Created: 79 tests across 9 modules**

**By Priority:**
- High: 3 modules (31 tests) - redis_adapter (6), command_handlers (16), mcp_server (9)
- Medium: 4 modules (36 tests) - voice_handler (11), session_cleanup (9), session_utils (6), ux_state (10)
- Low: 2 modules (13 tests) - events (7), session_lifecycle_logger (6)
- Skipped: 2 modules - metadata (Pydantic only), logging_config (config only)

**All tests marked with @pytest.mark.skip and TODO comments**

**Next Action:** Implement tests in priority order:
1. `test_command_handlers.py` (16 tests) - Central routing logic
2. `test_mcp_server.py` (9 tests) - External API surface
3. `test_redis_adapter.py` (6 tests) - Distributed system coordination
4. Continue with medium/low priority as needed
