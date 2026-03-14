# Implementation Plan: chartest-core-agent-coord

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/core/agent_coordinator/_coordinator.py` → `tests/unit/core/agent_coordinator/test__coordinator.py`
- [ ] Characterize `teleclaude/core/agent_coordinator/_fanout.py` → `tests/unit/core/agent_coordinator/test__fanout.py`
- [ ] Characterize `teleclaude/core/agent_coordinator/_helpers.py` → `tests/unit/core/agent_coordinator/test__helpers.py`
- [ ] Characterize `teleclaude/core/agent_coordinator/_incremental.py` → `tests/unit/core/agent_coordinator/test__incremental.py`
