# Spec Review Findings — hardcode-db-paths

**Verdict:** needs_work
**Reviewed at:** 2026-03-28
**Reviewer:** test-spec-reviewer

---

## Summary

No xfail test specs were delivered for this task. The `test_spec_build` audit entry has timestamps but `artifacts.test_specs.digest` is empty — no spec commits exist in the branch. The existing test suite touches the affected modules but contains only active (non-xfail) tests that exercise the **current** behavior, not the **intended post-change** behavior.

Requirements R1–R7 have zero corresponding expected-failure specs. This is a blocking deficiency: the builder has no behavioral contract to satisfy.

---

## Findings

### [CRITICAL-01] No xfail test specs delivered for any requirement

The `test_spec_build` artifact digest is empty. No expected-failure test files were committed. All seven requirements (R1–R7) lack a behavioral contract in the test suite. The builder has nothing to make green.

**Affected requirements:** R1, R2, R3, R4, R5, R6, R7

---

### [CRITICAL-02] R1 — No test for canonical DB path constants in paths.py

`tests/unit/test_paths.py` is a characterization test for `teleclaude/paths.py`. It asserts only the currently-existing constants (`TELECLAUDE_HOME`, `STATE_DIR`, etc.). There is no xfail test asserting that `MAIN_DB`, `MIRRORS_DB`, and `EVENTS_DB` (or equivalent names) exist and are derived from `TELECLAUDE_HOME`.

A builder who adds constants with the wrong name, wrong parent, or wrong derivation would have no automated check to catch the error.

**Required:** An xfail test in `tests/unit/test_paths.py` asserting each constant's name and its relationship to `TELECLAUDE_HOME`.

---

### [CRITICAL-03] R3 — Existing active test contradicts removal of resolve_db_path()

`tests/unit/mirrors/test_store.py::TestResolveDbPath` actively exercises `store_module.resolve_db_path()`. When the builder removes this function per R3, this test will **break** — causing CI to fail during implementation rather than before it.

There is no replacement xfail spec documenting what should happen after removal (i.e., a test that asserts `resolve_db_path` does not exist, or that call sites are absent). The test suite has a negative dependency on code that must be deleted.

**Required:**

1. An xfail test asserting the function no longer exists (e.g., `assert not hasattr(store_module, "resolve_db_path")`), or documentation that `TestResolveDbPath` is to be deleted entirely.
2. This must be coordinated with the plan so the builder knows to delete `TestResolveDbPath` as part of R3 delivery.

---

### [CRITICAL-04] R4 — No spec for get_session_context() db parameter removal

`tests/unit/mirrors/test_processors.py` mocks `get_session_context` with signatures including `db=None`:

```python
lambda session_id=None, transcript_path=None, db=None: SessionMirrorContext(...)
```

After R4 removes the `db` parameter from the real function, these lambda mocks would be passing an extra keyword argument if the production code is called through a non-mocked path. More critically, no xfail spec verifies that:

- `get_session_context` no longer accepts a `db` parameter
- call sites in `processors.py` no longer pass `db=`

A builder who removes `db` but forgets to update callers has no failing test to expose the omission.

**Required:** An xfail test asserting `get_session_context`'s signature lacks a `db` parameter (via `inspect.signature`) or asserting that its production call in `process_mirror_event` does not supply a `db` argument.

---

### [CRITICAL-05] R5 — No spec for events signals handler using events DB constant

`tests/unit/cli/telec/handlers/test_events_signals.py::test_handle_signals_status_prints_counts_and_last_ingest` patches the module injecting:

```python
"teleclaude.config": SimpleNamespace(
    config=SimpleNamespace(database=SimpleNamespace(path=Path("/tmp/test.db")))
)
```

After R5 fixes the handler to use the events DB constant from `paths.py` instead of `config.database.path`, this test must change. But no xfail spec exists asserting that:

- the handler connects to the events DB path (not the main DB)
- `config.database` is no longer accessed in the signals status handler

A broken implementation (handler still reads config.database.path) would pass the existing test and go undetected.

**Required:** An xfail test verifying `_handle_signals_status` opens a connection to the canonical events DB path (monkeypatching `paths.EVENTS_DB` rather than `teleclaude.config`).

---

### [IMPORTANT-06] R2 — No test spec for DatabaseConfig removal

No test verifies that `DatabaseConfig` has been removed from the config schema or that `config.database` is no longer accessible. A builder could skip R2 entirely without breaking any test.

**Required:** An xfail test asserting `DatabaseConfig` is not importable from `teleclaude.config` (raises `ImportError` or `AttributeError`) and that the top-level `Config` object has no `database` attribute.

---

### [IMPORTANT-07] R6 — No spec for monkeypatch target migration

No test verifies that tests which previously monkeypatched `config.database.path` must now monkeypatch the canonical constant (e.g., `paths.MIRRORS_DB`). R6 explicitly calls this out as a scope item, but there is no spec showing the required pattern. The builder has no test to enforce the correct isolation approach.

**Required:** At least one xfail test demonstrating the monkeypatching of `paths.MIRRORS_DB` produces the correct isolation behavior in the DB layer.

---

### [IMPORTANT-08] R7 — No test spec for Alembic env.py migration

No test verifies that `alembic/env.py` uses the canonical main DB constant. The Alembic path is a silent runtime failure: it would only break at actual migration time, not during the test suite. The success criteria (SC4) requires a passing test suite, but cannot catch an Alembic misconfiguration without a dedicated spec.

**Required:** An xfail test (or an integration-level check) asserting that `alembic/env.py` constructs its URL from `paths.MAIN_DB` rather than `config.database.path`.

---

### [MINOR-09] Prose-lock assertions in test_events_signals

`test_handle_signals_status_prints_counts_and_last_ingest` asserts:

```python
assert "12" in output
assert "2025-01-02T03:04:05Z" in output
```

Asserting on rendered output strings violates the output-text assertion guardrail. The value `12` should be asserted against the data structure returned by `get_signal_counts`, not against the text printed to stdout. This is an existing issue unrelated to this task but must not be carried forward in any new specs.

---

### [MINOR-10] Truthy-check assertion in test_events_signals

`test_handle_signals_status_reports_uninitialized_tables` asserts:

```python
assert capsys.readouterr().out.strip()
```

This passes for any non-empty string. A broken implementation that prints a single space would satisfy the assertion. Any replacement spec for this test must assert on a specific error signal (error code, exception class, or data flag) rather than truthy output presence.

---

## Required before re-review

1. Deliver xfail test specs for R1 through R7 as described above.
2. Coordinate deletion or replacement of `TestResolveDbPath` in `test_store.py` as part of R3 delivery.
3. Replace prose-lock and truthy-check patterns (findings 09, 10) in any test specs that touch `test_events_signals`.

The spec build must be rerun and the resulting tests committed before this review can be approved.
