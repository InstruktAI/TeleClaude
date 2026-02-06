# E2E Test Suite - Interaction Coverage Analysis

## Purpose

Map component interactions covered by each integration test to identify:

- Overlaps (duplication)
- Gaps (missing interaction coverage)
- Optimal test organization

## Component Interaction Map

### Key Components

1. **Telegram Adapter** - Telegram bot interface
2. **Redis Adapter** - Multi-computer communication
3. **UI Adapter** - Tmux UI interface
4. **AdapterClient** - Orchestrates all adapters
5. **Database (Db)** - Session persistence
6. **Tmux Bridge** - tmux operations
7. **Polling Coordinator** - Output polling & broadcasting
8. **Command Handlers** - Command execution logic
9. **MCP Server** - MCP tools for cross-computer ops
10. **Session Management** - Session lifecycle

---

## Test File Analysis

### test_ai_to_ai_session_init_e2e.py

- Redis → AdapterClient → Command Handlers → Db (session creation)
- Redis → AdapterClient → Tmux Bridge (session creation)
- Command Handlers → Tmux Bridge (/agent commands)

### test_command_e2e.py

- Command Handlers → Tmux Bridge → tmux (short + long)
- Polling → Tmux Bridge (capture)
- Polling → AdapterClient → Telegram (delivery)
- Failure path → AdapterClient.send_message (error surface)

### test_context_selector_e2e.py

- Context selector → docs index → output selection

### test_e2e_smoke.py

- API server cache notifications → WebSocket broadcast
- Session updates/removals → cache/event bus

### test_feedback_cleanup.py

- AdapterClient → Db (pending deletions)
- User input → cleanup logic → Telegram delete_message

### test_file_upload.py

- File handler → tmux bridge (path injection)
- File handler → AdapterClient → Telegram (status)
- File cleanup → Db + filesystem

### test_mcp_tools.py

- MCP Server → AdapterClient → Redis (remote)
- MCP Server → Db (list sessions)
- MCP Server → AdapterClient → Telegram (send file)

### test_multi_adapter_broadcasting.py

- AdapterClient → origin/observer routing
- Redis/UI adapters as observers
- Error propagation isolation

### test_output_download.py

- UI Adapter → output truncation → Telegram download metadata
- Telegram callback → transcript parsing → send_document → cleanup

### test_polling_restart.py

- Polling coordinator → guard + restart
- Process exit → polling stop

### test_process_exit_detection.py

- Polling → exit detection
- Session state persistence across restart

### test_projects_digest_refresh.py

- Cache → digest computation → refresh gating

### test_redis_adapter_warmup.py

- Redis adapter startup → snapshot refresh

### test_redis_heartbeat.py

- Redis heartbeat publishing → session metadata

### test_session_lifecycle.py

- Session cleanup → tmux kill + workspace cleanup + DB close

### test_state_machine_workflow.py

- Todo state machine → workflow transitions

### test_telec_cli_commands.py

- CLI parser → context selector (docs index + content)
- CLI parser → sync orchestrator (validate-only)
- CLI parser → project init
- Shell completion → docs flag suggestions

### test_voice_flow.py

- Voice handler → transcription → process_message
- Transcription failure → no tmux send

### test_worktree_preparation_integration.py

- Worktree setup → todo preparation workflow

---

## Current Gaps

- None critical. Remaining gaps should be represented as explicit use cases in `tests/E2E_USE_CASES.md` and tracked in `tests/integration/USE_CASE_COVERAGE.md`.
