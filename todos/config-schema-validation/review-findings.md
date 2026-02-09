# Review Findings — config-schema-validation

## Critical

1. **`jobs.when.every` accepts invalid/unsafe values and can break scheduling at runtime**
   - Evidence: `teleclaude/config/schema.py:7` and `teleclaude/config/schema.py:11` only enforce mode exclusivity, not duration format or minimum (`>= 1m`) from requirements.
   - Runtime path: `teleclaude/cron/runner.py:103` calls `_parse_duration` and `teleclaude/cron/runner.py:70` raises `ValueError` for bad strings; this exception is not handled in due-check flow (`teleclaude/cron/runner.py:330`).
   - Reproduced behavior: `every: "0m"` is accepted and immediately due on every run; `every: "bad"` loads but raises at runtime.
   - Why this matters: violates acceptance criteria for schema validation and allows one bad config value to break cron execution.

## Important

1. **`timezone` key is warned-but-accepted instead of rejected**
   - Evidence: `ProjectConfig` allows extras (`teleclaude/config/schema.py:77`) and loader only logs unknown keys (`teleclaude/config/loader.py:38`).
   - Reproduced behavior: config with top-level `timezone: UTC` validates successfully and appears in `model_extra`.
   - Why this matters: conflicts with acceptance criterion 10 (`timezone` must be rejected as unknown/deprecated).

2. **Unknown keys are not warned “at any level”; nested extras are silently dropped**
   - Evidence: warning only inspects root `model_extra` (`teleclaude/config/loader.py:38`), while nested models like `BusinessConfig`/`GitConfig` rely on default extra handling (`teleclaude/config/schema.py:40`, `teleclaude/config/schema.py:44`), which drops unknown fields without warning.
   - Why this matters: does not satisfy the requirement that unknown keys should warn for forward compatibility and operator visibility.

## Fixes Applied

### Critical #1: Job duration validation (27a07199)

- Added field validator `validate_every_format` for `JobWhenConfig.every`
- Validates duration format matches `^(\d+)([mhd])$` regex pattern
- Enforces minimum duration of 1 minute
- Prevents runtime `ValueError` when invalid duration reaches cron runner
- Test coverage: `test_job_every_invalid_duration_format`, `test_job_every_zero_duration`

### Important #1: Timezone key rejection (27a07199)

- Added "timezone" to disallowed keys in `ProjectConfig`, `GlobalConfig`, and `PersonConfig`
- Raises `ValueError` with clear message when timezone key is present
- Test coverage: `test_timezone_key_rejected_project`, `test_timezone_key_rejected_global`, `test_timezone_key_rejected_person`

### Important #2: Nested unknown keys warning (b4f5d4e2)

- Added `_warn_unknown_keys` helper function in loader that recursively traverses nested models
- Updated `BusinessConfig` and `GitConfig` to use `extra="allow"` for forward compatibility
- Warnings now emitted for unknown keys at all nesting levels
- Test coverage: `test_nested_unknown_keys_warning`

## Verdict

REQUEST CHANGES → FIXES APPLIED, READY FOR RE-REVIEW
