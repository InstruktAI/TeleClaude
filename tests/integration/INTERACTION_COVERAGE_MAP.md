# E2E Test Suite - Interaction Coverage Analysis

## Purpose
Map component interactions covered by each e2e test to identify:
- Overlaps (duplication)
- Gaps (missing interaction coverage)
- Optimal test organization

## Component Interaction Map

### Key Components
1. **Telegram Adapter** - Telegram bot interface
2. **Redis Adapter** - Multi-computer communication
3. **UI Adapter** - Terminal UI interface
4. **AdapterClient** - Orchestrates all adapters
5. **Database (Db)** - Session persistence
6. **Terminal Bridge** - tmux operations
7. **Polling Coordinator** - Output polling & broadcasting
8. **Command Handlers** - Command execution logic
9. **MCP Server** - MCP tools for cross-computer ops
10. **Session Management** - Session lifecycle

---

## Test File Analysis

### test_ai_to_ai_session_init_e2e.py
**Tests:** 3
**Interactions Covered:**
- Redis → AdapterClient → Command Handlers → Database (create session)
- Redis → AdapterClient → Terminal Bridge (session creation)
- Command Handlers → Terminal Bridge (/cd, /claude commands)

**Mocks:** Telegram (all), Redis (connection), Terminal (send_keys, tmux)
**Focus:** AI-to-AI session initialization flow

---

### test_command_e2e.py
**Tests:** 2
**Interactions Covered:**
- Command Handlers → Terminal Bridge → tmux (short-lived commands)
- Command Handlers → Terminal Bridge → tmux (long-running commands)
- Polling → Terminal Bridge (output capture)
- Polling → AdapterClient → Telegram (output delivery)

**Mocks:** Telegram (all), Terminal (send_keys, tmux)
**Focus:** Command execution patterns (short vs long-running)

---

### test_core.py
**Tests:** 3
**Interactions Covered:**
- Database CRUD operations (direct)
- Terminal Bridge → tmux (create, send_keys, capture, kill)

**Mocks:** Telegram (all in one test)
**Focus:** Core component functionality in isolation

**OVERLAP WARNING:** Terminal Bridge operations duplicated with other tests

---

### test_feedback_cleanup.py
**Tests:** 1
**Interactions Covered:**
- AdapterClient → Database (UX state management)
- AdapterClient → Telegram (message deletion)
- User input → cleanup logic

**Mocks:** Telegram (all)
**Focus:** Feedback message cleanup on user input

---

### test_file_upload.py
**Tests:** 4
**Interactions Covered:**
- File Handler → AdapterClient → Telegram (file upload)
- File Handler → Database (file tracking)
- Session cleanup → File deletion
- Process state → Upload rejection

**Mocks:** Telegram (all), Terminal (send_keys, tmux)
**Focus:** File upload and cleanup lifecycle

---

### test_full_flow.py
**Tests:** 3
**Interactions Covered:**
- Command execution → Polling → Output delivery (full chain)
- Terminal Bridge → tmux (direct command execution)
- Polling Coordinator → OutputPoller → AdapterClient

**Mocks:** Telegram (all), Terminal (send_keys, tmux)
**Focus:** Complete message → execution → output flow

**OVERLAP WARNING:** Duplicates test_command_e2e.py flow

---

### test_idle_notification.py
**Tests:** 4
**Interactions Covered:**
- Polling → timeout detection → notification
- AdapterClient → Database (UX state for notifications)
- Notification → cleanup on output resume

**Mocks:** Telegram (all), Terminal (send_keys, tmux)
**Focus:** Idle notification lifecycle

---

### test_mcp_tools.py
**Tests:** 8
**Interactions Covered:**
- MCP Server → AdapterClient → Redis (list computers, start session)
- MCP Server → Database (list sessions)
- MCP Server → AdapterClient → Telegram (send file, send notification)
- Request/response protocol via Redis

**Mocks:** Telegram (all), Redis (discover_peers, send_request, read_response)
**Focus:** MCP tool correctness

---

### test_multi_adapter_broadcasting.py
**Tests:** 5
**Interactions Covered:**
- Origin adapter → AdapterClient (message origin)
- Observer adapters → AdapterClient (broadcast receivers)
- UI adapter observation
- Redis adapter observation
- Error handling in observers

**Mocks:** Telegram (all), Redis (connection), UI (all)
**Focus:** Multi-adapter message broadcasting

---

### test_notification_hook.py
**Tests:** 1
**Interactions Covered:**
- MCP socket → notification protocol
- Hook system → MCP server

**Mocks:** Telegram (all), MCP socket communication
**Focus:** MCP notification hook integration

---

### test_polling_restart.py
**Tests:** 2
**Interactions Covered:**
- Process exit → polling stop
- New command → polling restart
- Polling guard (prevent duplicates)

**Mocks:** Telegram (all), Terminal (partial)
**Focus:** Polling lifecycle across commands

**CRITICAL:** Tests polling state management edge case

---

### test_process_exit_detection.py
**Tests:** 2
**Interactions Covered:**
- Polling → shell-return detection
- Database → UX state (process state tracking)
- Daemon restart → state persistence

**Mocks:** Telegram (all), Terminal (send_keys, tmux)
**Focus:** Process exit detection reliability

---

### test_redis_heartbeat.py
**Tests:** 2
**Interactions Covered:**
- Redis → heartbeat publishing
- Heartbeat → session metadata inclusion
- Session count limiting in heartbeat

**Mocks:** Telegram (all), Redis (connection)
**Focus:** Redis heartbeat mechanism

---

### test_send_message_flow.py
**Tests:** 2
**Interactions Covered:**
- MCP → Redis → remote session (send message)
- Command parsing

**Mocks:** Telegram (all), MCP methods (start_session, send_message, etc.)
**Focus:** Remote messaging API

**OVERLAP WARNING:** Heavy mocking makes this more of a unit test

---

### test_session_lifecycle.py
**Tests:** 4
**Interactions Covered:**
- Session close → cleanup (tmux, polling, database)
- Session close → idempotency
- Session close → database persistence
- Active polling → session close coordination

**Mocks:** Telegram (all), Terminal (send_keys, tmux)
**Focus:** Session cleanup lifecycle

---

## Interaction Coverage Matrix

| Component A → Component B | Covered By |
|---------------------------|------------|
| Telegram → AdapterClient → Command Handlers | test_command_e2e, test_full_flow |
| Command Handlers → Terminal Bridge | test_command_e2e, test_full_flow, test_ai_to_ai |
| Terminal Bridge → tmux | test_core, test_command_e2e, test_full_flow, test_ai_to_ai |
| Polling → Terminal Bridge | test_command_e2e, test_full_flow, test_polling_restart |
| Polling → AdapterClient → Telegram | test_command_e2e, test_full_flow, test_idle_notification |
| Redis → AdapterClient → Command Handlers | test_ai_to_ai_session_init |
| MCP Server → AdapterClient → Redis | test_mcp_tools |
| MCP Server → AdapterClient → Telegram | test_mcp_tools |
| File Handler → AdapterClient → Telegram | test_file_upload |
| Session close → cleanup | test_session_lifecycle |
| Multi-adapter broadcasting | test_multi_adapter_broadcasting |
| Redis heartbeat | test_redis_heartbeat |
| Process exit detection | test_process_exit_detection |
| Idle notification | test_idle_notification |
| Feedback cleanup | test_feedback_cleanup |

---

## Analysis Summary

### Major Overlaps
1. **test_command_e2e.py + test_full_flow.py**
   - Both test: Command execution → Polling → Output delivery
   - **Recommendation:** Consolidate into single comprehensive test

2. **test_core.py (terminal bridge tests)**
   - Terminal Bridge operations tested in isolation
   - Same operations tested in context by other tests
   - **Recommendation:** Remove from integration suite, move to unit tests

3. **test_send_message_flow.py**
   - Heavily mocked (all MCP methods)
   - More of a unit test than integration test
   - **Recommendation:** Move to unit tests or remove

### Gaps Identified
1. **Direct Database → AdapterClient interaction**
   - Session persistence across adapter restarts (partially in process_exit_detection)

2. **Error propagation chains**
   - Telegram API failure → AdapterClient error handling
   - Redis connection loss → fallback behavior

3. **Cross-adapter coordination**
   - Origin adapter failure while observers succeed
   - Partial broadcast scenarios

### Strengths
1. **Good coverage of critical paths:**
   - AI-to-AI session initialization (test_ai_to_ai)
   - Session lifecycle (test_session_lifecycle)
   - File upload lifecycle (test_file_upload)

2. **Edge cases well covered:**
   - Polling restart (test_polling_restart)
   - Process exit detection (test_process_exit_detection)
   - Idle notifications (test_idle_notification)

3. **Multi-adapter patterns:**
   - Broadcasting (test_multi_adapter_broadcasting)
   - Heartbeat (test_redis_heartbeat)

---

## Recommendations

### Remove/Consolidate
1. **test_core.py** → Move terminal bridge tests to unit tests
2. **test_send_message_flow.py** → Move to unit tests (too heavily mocked)
3. **test_full_flow.py** → Consolidate with test_command_e2e.py

### Keep (High Value)
1. **test_ai_to_ai_session_init_e2e.py** - Unique AI-to-AI flow
2. **test_command_e2e.py** - Core command execution patterns
3. **test_session_lifecycle.py** - Critical cleanup logic
4. **test_file_upload.py** - File handling lifecycle
5. **test_polling_restart.py** - Critical edge case
6. **test_process_exit_detection.py** - Critical reliability feature
7. **test_multi_adapter_broadcasting.py** - Multi-adapter coordination
8. **test_mcp_tools.py** - MCP API contract
9. **test_idle_notification.py** - UX feature
10. **test_feedback_cleanup.py** - UX cleanup
11. **test_redis_heartbeat.py** - Discovery mechanism
12. **test_notification_hook.py** - Hook integration

### Add (Fill Gaps)
1. **test_error_propagation.py** - Error handling across component boundaries
2. **test_adapter_failure_recovery.py** - Adapter failure scenarios
