# Review Findings — config-schema-validation

## Critical

1. **Config loader fails open on malformed YAML and unreadable files**
   - Evidence: `load_config()` catches broad exceptions and returns `model_class()` defaults in `teleclaude/config/loader.py:45`.
   - Evidence: `load_config()` fallback return in `teleclaude/config/loader.py:50` means consumers proceed with empty/default config instead of a validation error.
   - Reproduction: malformed YAML (`jobs:\n  bad: [`) returns a default `ProjectConfig` with `jobs == {}` instead of failing.
   - Impact: this preserves the original silent-misconfiguration failure mode the change set is intended to eliminate.

## Important

1. **Unknown-key warnings are incomplete and miss nested/list-based config objects**
   - Evidence: unknown-key traversal only recurses into nested `BaseModel` fields and `dict` values in `teleclaude/config/loader.py:21`; it does not recurse into lists.
   - Evidence: multiple nested schema models still use default extra handling (`ignore`) and therefore drop unknown keys without warning, e.g. `PersonEntry` (`teleclaude/config/schema.py:95`) and `SubscriptionsConfig` (`teleclaude/config/schema.py:119`).
   - Reproduction: global config with `people[0].extra_field` and person/global `subscriptions.foo` is accepted, those fields are dropped, and no unknown-key warning is emitted.
   - Impact: requirement for warning on unknown keys at any level is not fully met.

## Suggestions

1. Make loader read/parse failures explicit errors (or return a structured error object) so invalid files cannot silently degrade to defaults.
2. Extend unknown-key detection to list elements and align nested models with the warning strategy (`extra="allow"` + recursive warning walk, or explicit pre-validation warnings).

## Fixes Applied

### Critical Issue 1: Config loader fail-open behavior

- **Fix**: Changed loader to raise `ValueError` with clear message on YAML parse errors and file read failures
- **Commit**: 8de05f3d
- **Verification**: Hooks passed (lint + tests)

### Important Issue 1: Incomplete unknown-key warnings

- **Fix 1**: Added `extra="allow"` to all nested models (PersonEntry, OpsEntry, TelegramCreds, CredsConfig, NotificationsConfig, SubscriptionsConfig)
- **Fix 2**: Extended `_warn_unknown_keys` recursion to handle list elements
- **Commit**: 8ce93030
- **Verification**: Hooks passed (lint + tests)

## Verdict

REQUEST CHANGES
