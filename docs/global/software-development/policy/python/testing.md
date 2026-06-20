---
description: 'Python-specific testing idioms layered over the generic testing policy: pytest runner, file/marker conventions, snapshots, and the no-unit-test enforcement.'
visibility: 'public'
---

# Python Testing — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md

## Rules

1. **No unit tests.** Behavior is verified by functional and smoke tests; Python is a compiler-less
   language under the generic rule. `tools/lint/forbid_unit_tests.py` (pre-commit) only prevents the
   `tests/unit/` path from reappearing — a path guard, not a unit-test detector. A unit test placed
   in any other directory, or wearing a `@pytest.mark.functional` label, passes every automated
   check and is caught only at review, against `software-development/concept/functional-test-boundary`.
   The discipline lives in the definition and the review, not in the path guard.
2. **Test files mirror the feature spec.** A spec at `docs/project/spec/feature/<domain>/<slug>.md`
   is covered by `tests/<domain>/test_<slug>.py`. Contract-defining tooling (wrappers, git filters)
   is not tested — see the generic policy.
3. **Bind scenarios with the marker** `@pytest.mark.spec("<spec_id>", "<UC-id>")`.
   <!-- planned-change:isolate-process-meta-tests -->
   The functional/integration tier is a marker (`@pytest.mark.functional` / `@pytest.mark.integration`),
   never a directory.
   <!-- change:isolate-process-meta-tests -->
   The functional/integration/process tier is a marker (`@pytest.mark.functional` /
   `@pytest.mark.integration` / `@pytest.mark.process`), never a directory — a directory may
   _organize_ a tier's tests (e.g. `tests/process/`), but tier selection is always by marker. The
   `process` tier marks a test that drives a real OS subprocess across wall-clock deadlines.
   <!-- /planned-change:isolate-process-meta-tests -->
   Shared fixtures live in `tests/conftest.py`.
4. **Run via `uv run pytest`.** The harness is plain pytest plus declarative configuration — no
   watchdog, reaper, in-flight tracker, or custom wall code.
   <!-- planned-change:isolate-process-meta-tests -->
   Time budgets are enforced by
   `pytest-timeout` (`timeout=5`, `timeout_method="signal"` for the functional/integration tier) and
   the suite wall-clock ceiling by `session_timeout`, both in `[tool.pytest.ini_options]` as the
   single source; parallelism is `pytest-xdist` (`-n auto`).
   <!-- change:isolate-process-meta-tests -->
   Time budgets for the fast tier (functional/integration) are enforced by
   `pytest-timeout` (`timeout=5`, `timeout_method="signal"`) and the suite wall-clock ceiling by
   `session_timeout`, both in `[tool.pytest.ini_options]` as the single source; parallelism is
   `pytest-xdist` (`-n auto`). The fast tier excludes the `process` tier via `-m "not process"`, so a
   subprocess-timing test never starves under xdist. The `process` tier is the sanctioned retier
   destination for a test that holds a real OS subprocess across wall-clock deadlines: it runs as a
   separate serial stage (xdist cleared via `-o "addopts="`) under its own relaxed per-test timeout,
   so that budget is a constant of the process stage, never a larger number granted to a fast-tier
   test.
   <!-- /planned-change:isolate-process-meta-tests -->
   A per-test budget breach forcibly stops
   the offending test and names it by node id with a dumped traceback (signal method), per xdist
   worker — the one point a running test is interrupted, so in-flight identification lives here. The
   session ceiling is a graceful between-tests stop that emits `session-timeout: N sec exceeded` and
   never hard-kills a running test; a run that ends in a bare `Interrupted` with no named cause is
   itself a test-infrastructure defect. Budgets are non-negotiable
   constants: a test that exceeds its budget is fixed, split, or retiered, never granted a larger
   number. A test that can hang or leak is fixed (or moved to a self-cleaning integration test), not
   wrapped in harness code.
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
