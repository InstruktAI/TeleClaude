---
id: 'software-development/policy/python/testing'
type: 'policy'
scope: 'domain'
visibility: 'public'
description: 'Python-specific testing idioms layered over the generic testing policy: pytest runner, file/marker conventions, snapshots, and the no-unit-test enforcement.'
---

# Python Testing — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md

## Rules

1. **No unit tests.** `tests/unit/` does not exist and must not be created;
   `tools/lint/forbid_unit_tests.py` (pre-commit) blocks any `tests/unit/**/test_*.py`. Python is a
   compiler-less language under the generic rule — behavior is verified by functional and smoke tests.
2. **Test files mirror the feature spec.** A spec at `docs/project/spec/feature/<domain>/<slug>.md`
   is covered by `tests/feature/<domain>/test_<slug>.py`. Tests for repository tooling live under
   `tests/tooling/` and are exempt from the mirror.
3. **Bind scenarios with the marker** `@pytest.mark.spec("<spec_id>", "<UC-id>")`. The
   functional/integration tier is a marker (`@pytest.mark.functional` / `@pytest.mark.integration`),
   never a directory. Shared fixtures live in `tests/feature/conftest.py`.
4. **Run via `uv run pytest`.** The harness is plain pytest — no watchdog, reaper, in-flight tracker,
   per-tier timeout markers, or custom wall. A test that can hang or leak is fixed (or moved to a
   self-cleaning integration test), not wrapped in harness.
5. **Snapshots use `syrupy`** (`uv run pytest --snapshot-update`; CI never updates snapshots). The
   string-assertion paradigm is the generic policy's.
6. **Coverage and drift** are reported by `tools/lint/spec_coverage.py` against the scenario
   inventory.

## Rationale

- Python has no compiler to enforce unit-level correctness, so an agent-authored unit test grades its
  own code and drifts to green-theater. The generic policy's behavioral model applies in full; this
  snippet only fixes the Python idioms that realize it.

## Scope

- All Python code in this repository and in projects managed by this platform.

## Enforcement

- `tools/lint/forbid_unit_tests.py` (pre-commit) blocks any unit test.
- `tools/lint/spec_coverage.py` reports bound / unbound / duplicate / orphan / stale.

## Exceptions

- None. There is no sanctioned unit test in Python.
