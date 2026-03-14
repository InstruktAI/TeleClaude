# Implementation Plan: chartest-core-models

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/core/models/_adapter.py` → `tests/unit/core/models/test__adapter.py`
- [ ] Characterize `teleclaude/core/models/_context.py` → `tests/unit/core/models/test__context.py`
- [ ] Characterize `teleclaude/core/models/_session.py` → `tests/unit/core/models/test__session.py`
- [ ] Characterize `teleclaude/core/models/_snapshot.py` → `tests/unit/core/models/test__snapshot.py`
