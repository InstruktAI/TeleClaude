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

## Verdict

REQUEST CHANGES
