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

## Verdict

REQUEST CHANGES
