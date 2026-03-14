# Implementation Plan: chartest-core-adapter-client

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/core/adapter_client/_channels.py` → `tests/unit/core/adapter_client/test__channels.py`
- [ ] Characterize `teleclaude/core/adapter_client/_client.py` → `tests/unit/core/adapter_client/test__client.py`
- [ ] Characterize `teleclaude/core/adapter_client/_output.py` → `tests/unit/core/adapter_client/test__output.py`
- [ ] Characterize `teleclaude/core/adapter_client/_remote.py` → `tests/unit/core/adapter_client/test__remote.py`
