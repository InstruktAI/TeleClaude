# Review Findings — config-schema-validation

## Critical

- None.

## Important

1. **Validation failures are still swallowed by migrated consumers**
   - Evidence: `teleclaude/context_selector.py:148` catches all exceptions from `load_project_config()` and silently falls back to default domains at `teleclaude/context_selector.py:152`.
   - Evidence: `teleclaude/docs_index.py:404` catches all exceptions from `load_project_config()` and silently falls back to directory-name project naming at `teleclaude/docs_index.py:410`.
   - Concrete trace: with `teleclaude.yml` containing a disallowed key (`people: []`), `_load_project_domains()` returns default `{"software-development": .../docs}` and `get_project_name()` returns the folder name instead of surfacing validation failure.
   - Impact: this preserves silent misconfiguration behavior in two of the declared config consumers, which conflicts with the requirement to validate before interpretation and remove silent schema mismatches.

2. **No behavioral tests cover new scheduler execution paths (`when.every` / `when.at`)**
   - Evidence: new due logic exists in `teleclaude/cron/runner.py:99` through `teleclaude/cron/runner.py:127`.
   - Evidence: tests only cover schema parsing and message construction (`tests/unit/test_config_schema.py`, `tests/unit/test_cron_runner_job_contract.py`); there are no tests asserting `_is_due()` behavior for `when.every`, `when.at`, weekday filtering, or multi-time handling.
   - Impact: acceptance criterion for scheduler compatibility is not verified at runtime behavior level, creating regression risk in actual scheduling decisions.

## Suggestions

1. In `context_selector` and `docs_index`, avoid bare silent fallback on config validation errors; either propagate or log and fail explicitly so misconfiguration is observable.
2. Add targeted unit tests for `_is_due()` covering `every`, `at` (single and list), `weekdays`, and timezone-local wall-clock boundaries.

## Fixes Applied

1. **Validation failures now propagate in context_selector and docs_index**
   - Fix: Replaced silent exception catching with explicit error propagation in `_load_project_domains()` (context_selector.py:148-152) and `get_project_name()` (docs_index.py:404-410).
   - Commit: 8cf62b58
   - Verification: Config validation failures now raise immediately with logged error details instead of silently falling back to defaults.

2. **Added comprehensive behavioral tests for \_is_due() scheduler execution paths**
   - Fix: Created `tests/unit/test_cron_runner_is_due.py` with 8 tests covering:
     - `when.every` interval-based scheduling (elapsed time checks)
     - `when.at` single time scheduling (wall-clock time comparisons)
     - `when.at` multiple times scheduling (any matching time triggers)
     - weekdays filtering with `when.at`
     - timezone-local wall-clock boundaries
     - before/after scheduled time boundary conditions
   - Commit: c15fb974
   - Verification: All tests pass, confirming runtime scheduler behavior matches design intent.

## Verdict

REQUEST CHANGES
