# Implementation Plan: chartest-cli-telec

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [x] Characterize `teleclaude/cli/telec/_run_tui.py` → `tests/unit/cli/telec/test__run_tui.py`
- [x] Characterize `teleclaude/cli/telec/_shared.py` → `tests/unit/cli/telec/test__shared.py`
- [x] Characterize `teleclaude/cli/telec/handlers/auth_cmds.py` → `tests/unit/cli/telec/handlers/test_auth_cmds.py`
- [x] Characterize `teleclaude/cli/telec/handlers/bugs.py` → `tests/unit/cli/telec/handlers/test_bugs.py`
- [x] Characterize `teleclaude/cli/telec/handlers/config.py` → `tests/unit/cli/telec/handlers/test_config.py`
- [x] Characterize `teleclaude/cli/telec/handlers/content.py` → `tests/unit/cli/telec/handlers/test_content.py`
- [x] Characterize `teleclaude/cli/telec/handlers/demo.py` → `tests/unit/cli/telec/handlers/test_demo.py`
- [x] Characterize `teleclaude/cli/telec/handlers/docs.py` → `tests/unit/cli/telec/handlers/test_docs.py`
- [x] Characterize `teleclaude/cli/telec/handlers/events_signals.py` → `tests/unit/cli/telec/handlers/test_events_signals.py`
- [x] Characterize `teleclaude/cli/telec/handlers/history.py` → `tests/unit/cli/telec/handlers/test_history.py`
- [x] Characterize `teleclaude/cli/telec/handlers/memories.py` → `tests/unit/cli/telec/handlers/test_memories.py`
- [x] Characterize `teleclaude/cli/telec/handlers/misc.py` → `tests/unit/cli/telec/handlers/test_misc.py`
- [x] Characterize `teleclaude/cli/telec/handlers/roadmap.py` → `tests/unit/cli/telec/handlers/test_roadmap.py`
- [x] Characterize `teleclaude/cli/telec/handlers/todo.py` → `tests/unit/cli/telec/handlers/test_todo.py`
- [x] Characterize `teleclaude/cli/telec/help.py` → `tests/unit/cli/telec/test_help.py`
- [x] Characterize `teleclaude/cli/telec/surface.py` → `tests/unit/cli/telec/test_surface.py`
- [x] Characterize `teleclaude/cli/telec/surface_types.py` → `tests/unit/cli/telec/test_surface_types.py`
- [x] Characterize `teleclaude/cli/tool_commands/infra.py` → `tests/unit/cli/tool_commands/test_infra.py`
- [x] Characterize `teleclaude/cli/tool_commands/sessions.py` → `tests/unit/cli/tool_commands/test_sessions.py`
- [x] Characterize `teleclaude/cli/tool_commands/todo.py` → `tests/unit/cli/tool_commands/test_todo.py`
