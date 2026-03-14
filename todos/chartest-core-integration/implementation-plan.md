# Implementation Plan: chartest-core-integration

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/core/integration/authorization.py` → `tests/unit/core/integration/test_authorization.py`
- [ ] Characterize `teleclaude/core/integration/blocked_followup.py` → `tests/unit/core/integration/test_blocked_followup.py`
- [ ] Characterize `teleclaude/core/integration/checkpoint.py` → `tests/unit/core/integration/test_checkpoint.py`
- [ ] Characterize `teleclaude/core/integration/event_store.py` → `tests/unit/core/integration/test_event_store.py`
- [ ] Characterize `teleclaude/core/integration/events.py` → `tests/unit/core/integration/test_events.py`
- [ ] Characterize `teleclaude/core/integration/formatters.py` → `tests/unit/core/integration/test_formatters.py`
- [ ] Characterize `teleclaude/core/integration/lease.py` → `tests/unit/core/integration/test_lease.py`
- [ ] Characterize `teleclaude/core/integration/queue.py` → `tests/unit/core/integration/test_queue.py`
- [ ] Characterize `teleclaude/core/integration/readiness_projection.py` → `tests/unit/core/integration/test_readiness_projection.py`
- [ ] Characterize `teleclaude/core/integration/runtime.py` → `tests/unit/core/integration/test_runtime.py`
- [ ] Characterize `teleclaude/core/integration/service.py` → `tests/unit/core/integration/test_service.py`
- [ ] Characterize `teleclaude/core/integration/step_functions.py` → `tests/unit/core/integration/test_step_functions.py`
