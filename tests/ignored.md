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

### teleclaude/transport/redis_transport.py

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

## Deleted Test Files

### TUI curses-era tests (deleted 2026-03-03)

The following files were deleted because they tested the pre-Textual curses TUI API
(`get_render_lines`, `flat_items`, `scroll_offset`, curses attrs). Every test was
already skip-marked and none had executed since the Textual migration (c680e05c).

| File | Tests | Coverage gap |
|---|---|---|
| `test_tui_sessions_view.py` | 62 | Sessions view rendering, keybinds, sticky/preview interactions |
| `test_tui_preparation_view.py` | 16 | Preparation view rendering, status display, depth indentation |
| `test_tui_app.py` | 9 | WebSocket event routing, auto-select, theme drift |
| `test_tui_view_snapshots.py` | 6 | Visual snapshot regression |
| `test_preparation_view.py` | 2 | Enter/prepare key modal prefill |
| `test_sessions_view.py` | 3 | Activity idle marking, enter toggle, sticky list |

**Total: 98 tests deleted, 0 were executing.**

New Textual-based TUI tests need to be written to restore this coverage.
