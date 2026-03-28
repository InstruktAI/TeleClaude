# Spec Review Findings — activation-trigger

**Verdict:** approve
**Reviewed at:** 2026-03-28
**Round:** 3
**Findings:** 2 (0 Critical, 2 Important)

---

## Summary

Round 2 addressed all 6 findings from round 1. Five xfail spec files now exist covering
R1–R9 with 59 tests. The suite stays green (all xfail). Two well-placed files in
`tests/unit/resource_validation/` provide strong R1 and R2 coverage. The R3/R4 distribution
spec and R5–R9 content spec are solid. One redundant file (`tests/unit/test_activation_trigger_validation_spec.py`)
duplicates R1/R2 coverage and contains a reference to a non-existent function — flagged below
as Important findings for cleanup during the build phase. The behavioral coverage is
sufficient to drive TDD.

---

## F-01 — Important: Redundant R1/R2 coverage in top-level spec file

**File:** `tests/unit/test_activation_trigger_validation_spec.py`
**Policy:** Testing policy rule 19 — "a function has one test home. Do not test the same
function from multiple test files."

This file duplicates coverage already provided by:

- `tests/unit/resource_validation/test_unified_severity_spec.py` (R1)
- `tests/unit/resource_validation/test_activation_trigger_validation_spec.py` (R2)

The resource_validation/ files are better placed (mirror the source module structure),
use the correct post-R1 API (`clear_errors()`, `get_errors()`), and are more thorough.

The top-level file has one unique contribution: checking `get_warnings` absence at the
`resource_validation` _package_ level (the `__init__.py` re-export surface), vs. the
`_models` module level tested in the resource_validation/ file. This is valuable but
belongs in `test_unified_severity_spec.py`, not in a separate file.

**Action for builder:** Delete `tests/unit/test_activation_trigger_validation_spec.py`.
Add one test to `TestWarningAPIRemoved` in `test_unified_severity_spec.py` asserting
`not hasattr(resource_validation_module, "get_warnings")` at the package level.

---

## F-02 — Important: Non-existent `sync._run_validate` in top-level spec

**File:** `tests/unit/test_activation_trigger_validation_spec.py:183`
**Function called:** `sync._run_validate(tmp_path, warn_only=True)`

`_run_validate` does not exist in `teleclaude/sync.py`. The public API is `sync.sync()`.
This test would fail with `AttributeError`, not a behavioral assertion failure — it can
never pass regardless of implementation.

The equivalent test in `test_unified_severity_spec.py::TestSyncWarnOnlyLeniencyPreserved`
correctly uses `sync.sync()` with proper monkeypatching. This finding is resolved by F-01's
action (delete the file).

---

## Coverage Matrix

| Requirement | Description                           | Coverage                                                                     |
| ----------- | ------------------------------------- | ---------------------------------------------------------------------------- |
| R1          | Unified validation severity           | ✅ `test_unified_severity_spec.py` — 9 tests (API, removal, adaptation)      |
| R2          | `activation_trigger` field validation | ✅ `test_activation_trigger_validation_spec.py` — 5 tests (4 boundary paths) |
| R3          | Activatable Procedures in AGENTS.md   | ✅ `test_activation_trigger_distribution_spec.py` — 5 tests                  |
| R4          | Automatic baseline exclusion          | ✅ `test_activation_trigger_distribution_spec.py` — 2 tests                  |
| R5          | Baseline progressive cleanup          | ✅ `test_activation_trigger_content_spec.py` — 6 parametrized tests          |
| R6          | Procedure activation annotations      | ✅ `test_activation_trigger_content_spec.py` — 11 parametrized tests         |
| R7          | Skill-authoring procedure update      | ✅ `test_activation_trigger_content_spec.py` — 2 tests                       |
| R8          | Skill-creator skill deletion          | ✅ `test_activation_trigger_content_spec.py` — 1 test                        |
| R9          | Schema documentation                  | ✅ `test_activation_trigger_content_spec.py` — 3 tests                       |

## Spec Quality Assessment

**Strengths:**

- All four R2 boundary conditions (accept on procedure, reject on non-procedure, reject
  empty, reject non-string) are covered with dedicated tests.
- R1 specs correctly test both the new API surface (`clear_errors`/`get_errors`/`_error`)
  and the removal of the old API (`_warn`/`get_warnings`/`clear_warnings`).
- R1 adaptation specs (F-02, F-03, F-06 from round 1) are addressed: third-party validation
  uses errors, sync leniency asserts on return values not stdout prose.
- R3/R4 distribution specs construct realistic fixture trees and test structural ordering,
  trigger text presence, and baseline exclusion — the right level of abstraction.
- R6 exact-match assertions on trigger text are appropriate since the trigger strings are
  execution-significant (agents consume them for capability discovery).
- All 59 tests xfail cleanly. Suite stays green.

**Acceptable trade-offs:**

- R3/R4 tests call `distribute._render_progressive_index()` and `distribute._write_project_agents()`
  (private functions). These are the only reasonable entry points below the CLI. The alternative
  (testing through `main()`) would require subprocess invocation with no behavioral advantage.
- R5–R9 tests access the real filesystem (repo root, `~/.teleclaude/docs/`). This is appropriate
  for content-verification specs where the requirement is about actual file state.
