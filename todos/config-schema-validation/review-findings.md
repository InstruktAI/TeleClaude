# Review Findings — config-schema-validation

## Critical

1. **Telegram adapter no longer starts in env-token setups unless `config.creds.telegram` is present**
   - Evidence: startup gate changed to `if config.creds.telegram` in `teleclaude/core/adapter_client.py:160`, while the adapter itself still authenticates from env (`teleclaude/adapters/telegram_adapter.py:139`).
   - Compatibility gap: `config.sample.yml:1` through `config.sample.yml:148` contains no `creds` section, so standard/sample config users with only `TELEGRAM_BOT_TOKEN` are now gated off.
   - Reproduced behavior: with `TELEGRAM_BOT_TOKEN` set, `config.creds.telegram=None`, and Redis disabled, `AdapterClient.start()` raises `ValueError: No adapters started`.
   - Impact: this is a runtime regression unrelated to schema validation and can prevent Telegram operation entirely.

## Important

1. **`jobs.when.at` values are not schema-validated as `HH:MM`**
   - Evidence: `JobWhenConfig` validates `every` but has no validator for `at` in `teleclaude/config/schema.py:6` through `teleclaude/config/schema.py:37`.
   - Runtime behavior: invalid values are accepted by schema and only logged later in scheduler path (`teleclaude/cron/runner.py:125` through `teleclaude/cron/runner.py:127`), e.g. `at: "99:99"` loads successfully.
   - Impact: violates requirement/plan expectation that invalid `when.at` should be rejected during validation.

2. **Unknown-key warning coverage is incomplete for job-level configs**
   - Evidence: warnings depend on `model_extra` traversal (`teleclaude/config/loader.py:16` through `teleclaude/config/loader.py:29`), but `JobScheduleConfig`/`JobWhenConfig` do not allow extras (`teleclaude/config/schema.py:40` through `teleclaude/config/schema.py:56`), so unknown keys are dropped silently.
   - Reproduced behavior: `jobs.bad.unknown_job_key: true` is ignored with no warning, while `business.unknown_*` does warn.
   - Impact: does not satisfy the requirement to warn on unknown keys at any level.

## Suggestions

1. Add explicit `at` format validation (`HH:MM`, 00-23/00-59) in `JobWhenConfig`.
2. Align adapter startup condition with actual auth contract (env token) or document and migrate config schema/sample to require `creds.telegram`.
3. Ensure unknown-key warning strategy covers job models (either `extra="allow"` + warnings, or explicit pre-validators that warn on unknown fields).

## Verdict

REQUEST CHANGES
