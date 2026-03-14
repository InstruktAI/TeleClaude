# Implementation Plan: chartest-core-tmux

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/core/tmux_bridge/_keys.py` → `tests/unit/core/tmux_bridge/test__keys.py`
- [ ] Characterize `teleclaude/core/tmux_bridge/_pane.py` → `tests/unit/core/tmux_bridge/test__pane.py`
- [ ] Characterize `teleclaude/core/tmux_bridge/_session.py` → `tests/unit/core/tmux_bridge/test__session.py`
- [ ] Characterize `teleclaude/core/tmux_bridge/_subprocess.py` → `tests/unit/core/tmux_bridge/test__subprocess.py`
