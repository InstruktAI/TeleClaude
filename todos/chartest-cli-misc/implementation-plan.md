# Implementation Plan: chartest-cli-misc

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [x] Characterize `teleclaude/cli/api_client.py` → `tests/unit/cli/test_api_client.py`
- [x] Characterize `teleclaude/cli/config_cli.py` → `tests/unit/cli/test_config_cli.py`
- [x] Characterize `teleclaude/cli/config_cmd.py` → `tests/unit/cli/test_config_cmd.py`
- [x] Characterize `teleclaude/cli/config_handlers.py` → `tests/unit/cli/test_config_handlers.py`
- [x] Characterize `teleclaude/cli/demo_validation.py` → `tests/unit/cli/test_demo_validation.py`
- [x] Characterize `teleclaude/cli/editor.py` → `tests/unit/cli/test_editor.py`
- [x] Characterize `teleclaude/cli/models.py` → `tests/unit/cli/test_models.py`
- [x] Characterize `teleclaude/cli/session_auth.py` → `tests/unit/cli/test_session_auth.py`
- [x] Characterize `teleclaude/cli/tool_client.py` → `tests/unit/cli/test_tool_client.py`
- [x] Characterize `teleclaude/cli/watch.py` → `tests/unit/cli/test_watch.py`
