# Ignored Code Files

This file documents source files that don't have dedicated unit tests and why.

## Files Without Unit Tests

### teleclaude/core/models.py
**Reason**: Simple dataclasses with no business logic.
- Testing object creation tests Python's type system, not our code
- Serialization (to_dict/from_dict) tested through integration tests (database round-trips)
- Migration logic tested implicitly when sessions are created/restored from database

### teleclaude/core/metadata.py
**Reason**: Simple dataclasses (MessageMetadata, ChannelMetadata, AdapterMetadata).
- No business logic to test
- Type safety enforced by mypy

### teleclaude/core/events.py
**Reason**: Event type definitions (enums, dataclasses).
- No business logic to test

### teleclaude/constants.py
**Reason**: Configuration constants only.
- No logic to test

### teleclaude/logging_config.py
**Reason**: Logging configuration only.
- No business logic to test

### teleclaude/core/ux_state.py
**Reason**: Simple state management dataclass.
- Tested implicitly through integration tests

### teleclaude/adapters/redis_adapter.py
**Reason**: Integration tested.
- Covered by tests/integration/test_redis_heartbeat.py
- Covered by tests/integration/test_multi_adapter_broadcasting.py

### teleclaude/core/session_cleanup.py
**Reason**: Integration tested.
- Covered by tests/integration/test_session_lifecycle.py

### teleclaude/core/voice_message_handler.py
**Reason**: Integration tested.
- Requires real Whisper API interaction
- Covered by end-to-end tests

### teleclaude/mcp_server.py
**Reason**: Integration tested.
- Covered by tests/integration/test_mcp_tools.py
- Requires running MCP server

### teleclaude/core/session_lifecycle_logger.py
**Reason**: Logging utility with no business logic.
- Tested implicitly through session lifecycle tests
