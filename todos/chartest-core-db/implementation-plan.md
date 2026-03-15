# Implementation Plan: chartest-core-db

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [x] Characterize `teleclaude/core/db/_base.py` → `tests/unit/core/db/test__base.py`
- [x] Characterize `teleclaude/core/db/_hooks.py` → `tests/unit/core/db/test__hooks.py`
- [x] Characterize `teleclaude/core/db/_inbound.py` → `tests/unit/core/db/test__inbound.py`
- [x] Characterize `teleclaude/core/db/_links.py` → `tests/unit/core/db/test__links.py`
- [x] Characterize `teleclaude/core/db/_listeners.py` → `tests/unit/core/db/test__listeners.py`
- [x] Characterize `teleclaude/core/db/_operations.py` → `tests/unit/core/db/test__operations.py`
- [x] Characterize `teleclaude/core/db/_rows.py` → `tests/unit/core/db/test__rows.py`
- [x] Characterize `teleclaude/core/db/_sessions.py` → `tests/unit/core/db/test__sessions.py`
- [x] Characterize `teleclaude/core/db/_settings.py` → `tests/unit/core/db/test__settings.py`
- [x] Characterize `teleclaude/core/db/_sync.py` → `tests/unit/core/db/test__sync.py`
- [x] Characterize `teleclaude/core/db/_tokens.py` → `tests/unit/core/db/test__tokens.py`
- [x] Characterize `teleclaude/core/db/_webhooks.py` → `tests/unit/core/db/test__webhooks.py`
