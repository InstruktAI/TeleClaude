# Review Findings: runtime-settings-tts-toggle

## Critical

- Unknown settings keys are silently accepted when `tts.enabled` is also present, violating the requirement that unknown keys must return `400`.
  - Evidence: `SettingsPatchDTO`/`TTSSettingsPatchDTO` do not forbid extra fields, so unknown keys are dropped during request parsing (`teleclaude/api_models.py:331`, `teleclaude/api_models.py:339`).
  - The endpoint then applies the remaining valid fields and returns `200` (`teleclaude/api_server.py:759`).
  - Concrete repro (from this review):
    - `PATCH /settings {"foo":"bar","tts":{"enabled":false}}` returns `200`
    - `PATCH /settings {"tts":{"enabled":false,"voice":"nova"}}` returns `200`

## Important

- Review precondition not met: implementation-plan still has unchecked validation tasks (`todos/runtime-settings-tts-toggle/implementation-plan.md:117`, `todos/runtime-settings-tts-toggle/implementation-plan.md:118`).
- Build gates are not fully complete (`Working tree clean` remains unchecked), so the build-quality precondition is not satisfied (`todos/runtime-settings-tts-toggle/quality-checklist.md:19`).
- Tests miss the contract-breaking scenario where unknown keys are combined with valid keys; current negative test only covers the all-unknown payload path (`tests/unit/test_runtime_settings.py:155`).

## Suggestions

- Enforce strict request contracts at the API boundary (`extra="forbid"` for patch DTOs) and add tests for:
  - unknown top-level key + valid `tts.enabled`
  - unknown nested `tts` key + valid `enabled`
  - unknown-only payload

Verdict: REQUEST CHANGES
