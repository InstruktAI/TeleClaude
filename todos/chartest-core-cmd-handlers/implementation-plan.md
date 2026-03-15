# Implementation Plan: chartest-core-cmd-handlers

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [x] Characterize `teleclaude/core/command_handlers/_agent.py` → `tests/unit/core/command_handlers/test__agent.py`
- [x] Characterize `teleclaude/core/command_handlers/_keys.py` → `tests/unit/core/command_handlers/test__keys.py`
- [x] Characterize `teleclaude/core/command_handlers/_message.py` → `tests/unit/core/command_handlers/test__message.py`
- [x] Characterize `teleclaude/core/command_handlers/_session.py` → `tests/unit/core/command_handlers/test__session.py`
- [x] Characterize `teleclaude/core/command_handlers/_utils.py` → `tests/unit/core/command_handlers/test__utils.py`
