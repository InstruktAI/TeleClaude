# Implementation Plan: chartest-core-next-machine

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [x] Characterize `teleclaude/core/next_machine/build_gates.py` → `tests/unit/core/next_machine/test_build_gates.py`
- [x] Characterize `teleclaude/core/next_machine/create.py` → `tests/unit/core/next_machine/test_create.py`
- [x] Characterize `teleclaude/core/next_machine/delivery.py` → `tests/unit/core/next_machine/test_delivery.py`
- [x] Characterize `teleclaude/core/next_machine/git_ops.py` → `tests/unit/core/next_machine/test_git_ops.py`
- [x] Characterize `teleclaude/core/next_machine/icebox.py` → `tests/unit/core/next_machine/test_icebox.py`
- [x] Characterize `teleclaude/core/next_machine/output_formatting.py` → `tests/unit/core/next_machine/test_output_formatting.py`
- [x] Characterize `teleclaude/core/next_machine/prepare.py` → `tests/unit/core/next_machine/test_prepare.py`
- [x] Characterize `teleclaude/core/next_machine/prepare_events.py` → `tests/unit/core/next_machine/test_prepare_events.py`
- [x] Characterize `teleclaude/core/next_machine/prepare_steps.py` → `tests/unit/core/next_machine/test_prepare_steps.py`
- [x] Characterize `teleclaude/core/next_machine/roadmap.py` → `tests/unit/core/next_machine/test_roadmap.py`
- [x] Characterize `teleclaude/core/next_machine/slug_resolution.py` → `tests/unit/core/next_machine/test_slug_resolution.py`
- [x] Characterize `teleclaude/core/next_machine/state_io.py` → `tests/unit/core/next_machine/test_state_io.py`
- [x] Characterize `teleclaude/core/next_machine/work.py` → `tests/unit/core/next_machine/test_work.py`
- [x] Characterize `teleclaude/core/next_machine/worktrees.py` → `tests/unit/core/next_machine/test_worktrees.py`
