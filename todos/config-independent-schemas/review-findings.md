# Review Findings: config-independent-schemas

**Round:** 1
**Reviewer:** Claude (Sonnet 4.6)
**Diff base:** `git merge-base HEAD main`

---

## Lanes Executed

| Lane                    | Status |
| ----------------------- | ------ |
| scope                   | ✓ run  |
| code                    | ✓ run  |
| paradigm                | ✓ run  |
| principles              | ✓ run  |
| security                | ✓ run  |
| tests                   | ✓ run  |
| errors (silent failure) | ✓ run  |
| types                   | ✓ run  |
| comments                | ✓ run  |
| logging                 | ✓ run  |
| demo                    | ✓ run  |
| docs                    | ✓ run  |
| simplify                | ✓ run  |

---

## Critical

_None._

---

## Important

### I-1 — Out-of-scope changes bundled in branch

**Lane:** scope
**Files:** `teleclaude/core/identity.py:269`, `teleclaude/utils/transcript/_parsers.py:18-23`, `tests/unit/core/test_identity.py`, `tests/unit/utils/transcript/test__parsers.py`
**Commit:** `041acdccf fix(identity,transcript): default unresolved identity to customer, include string summary in reasoning`

Two behavioral changes are included in this branch that are not part of the `config-independent-schemas` requirements:

1. **`identity.py`** — `return IdentityContext()` changed to `return IdentityContext(person_role=HUMAN_ROLE_CUSTOMER)`. This changes the default fallback identity for unresolved terminal origin to the customer role. This is a distinct bug fix with no relationship to config schema independence.

2. **`_parsers.py`** — `_extract_codex_reasoning_text` now includes string-typed summary items in the reasoning output (dict-typed items continue to be skipped). This changes Codex reasoning display behavior. Corresponding test was renamed and assertion updated.

Both have tests and appear correct, but they are unrequested changes outside the stated scope. They must be either:

- Moved to a separate work item (preferred), or
- Explicitly acknowledged in `requirements.md` scope under an addendum.

---

### I-2 — Missing GlobalConfig migration backward-compat test

**Lane:** tests
**File:** `teleclaude/config/schema.py:342-352` (the `migrate_git_checkout_root` validator)

The requirements constraint states: _"checkout_root must continue to work when set in existing global configs. If the YAML key path changes, the old path must still be accepted during a transition period."_

The `migrate_git_checkout_root` validator is the mechanism for this backward compat. It is implemented but has no test. No test in `test_config_independent_schemas.py` or `test_schema.py` validates:

```python
config = GlobalConfig.model_validate({"git": {"checkout_root": "/srv/repos"}})
assert config.checkout_root == "/srv/repos"
```

`test_backward_compat_checkout_root_on_project_config` (line 271) covers `ProjectConfig` backward compat only. `test_load_checkout_root_reads_from_global_config` (line 253) mocks `load_global_config` with a pre-built `GlobalConfig` object — it never exercises the YAML-loading migration path.

This is an untested constraint requirement. The migration validator must be covered.

---

## Suggestions

### S-1 — Duplicate computation in `load_app_config`

**File:** `teleclaude/config/loader.py:103-111`

`teleclaude_yml = workspace / "teleclaude.yml"` is computed twice — once in the `if` branch and once in the `else` branch. This is harmless but can be hoisted to before the conditional:

```python
teleclaude_yml = workspace / "teleclaude.yml"
if _is_person_workspace(workspace):
    if teleclaude_yml.exists():
        person_config = load_person_config(teleclaude_yml)
elif teleclaude_yml.exists():
    project_config = load_project_config(teleclaude_yml)
```

---

## Passing lanes (no findings)

### Code

All in-scope production changes are correct:

- `GlobalConfig` inheritance from `ProjectConfig` is cleanly broken; `BaseModel` base is correct.
- `extra="allow"` on `GlobalConfig` provides backward compat for existing YAML files with project-level keys.
- `migrate_git_checkout_root` validator runs before `reject_disallowed_keys` (definition order for `mode="before"` validators on the same class). The disallowed set for `GlobalConfig` does not include `git`, so ordering is safe in either case.
- `save_project_config` implements atomic write (temp + rename) correctly; cleans up temp file on failure.
- `load_app_config` correctly returns `project=None` for person workspaces and for unrecognized paths.
- `_resolve_domain_paths` correctly extracted as a pure helper; `_load_project_domains` refactored to use it; backward-compat path preserved.
- `build_context_output` correctly falls back to legacy path when `config` is `None`.
- `BusinessConfig.domains` defaults to `{}` (never None), so `config.project.business.domains` access is safe.
- `GitConfig` correctly becomes an empty-body model with `extra="allow"`.

### Paradigm

- AppConfig frozen dataclass follows the established pattern; consistent with the atomic write pattern used by global/person configs.
- `_resolve_domain_paths` extraction follows SRP and avoids duplicating logic.

### Principles

- No unjustified fallbacks. The `or project_root.name` fallback is intentional design (`project_name` is optional).
- No DIP violations; no god-object patterns introduced.
- No silent degradations in new code paths.

### Security

- No secrets committed.
- No injection vulnerabilities.
- Pydantic validates at config load boundaries.
- No PII in log messages.

### Tests

All 78 config-directory tests pass. All 32 tests across the other changed modules pass. All spec tests in `test_config_independent_schemas.py` have `xfail` markers removed and pass actively. The test for `test_expands_env_vars_and_warns_about_unknown_keys` correctly adds the `root.git` unknown-key warning to its assertion. See I-2 for the one coverage gap.

### Errors / Silent failures

`save_project_config` re-raises after temp-file cleanup. `load_app_config` propagates all exceptions from loaders. No log-and-continue patterns introduced.

### Types

Explicit types on all new functions. `AppConfig | None = None` parameter on `build_context_output` is correct. Frozen dataclass enforces immutability. `# pyright: ignore[reportAttributeAccessIssue]` in `test_loader.py` correctly acknowledges accessing an extra field via Pydantic.

### Comments

All new docstrings accurately describe current behavior. The inline comment `# Resolve project name from config when available (avoids interior config loading)` is accurate. `GlobalConfig` docstring correctly changed from "extending project config" to just "Global-level configuration."

### Logging

No ad-hoc debug probes. Existing `logger.error` in `_load_project_domains` preserved correctly.

### Demo

Five executable bash blocks present. Commands reference real implementations. Block 4 (`git commit --dry-run --allow-empty`) does exercise pre-commit hooks and is valid. No fabricated output.

### Docs

No new CLI subcommands or user-facing config surface introduced. No help text or config spec updates required.

### Simplify

Code is clean and readable. One minor duplication noted in S-1.

---

## Fixes Applied

### I-1 — Scope acknowledgment added

Added a "Scope addendum — incidental bug fixes in branch" section to
`todos/config-independent-schemas/requirements.md` explicitly documenting both
out-of-scope changes (identity default fallback and Codex reasoning string items)
with rationale for inclusion.

**Commit:** `3f5d90111`

### I-2 — GlobalConfig migration test added

Added two tests to `TestCheckoutRootRelocation` in
`tests/unit/config/test_config_independent_schemas.py`:

1. `test_global_config_migrates_git_checkout_root` — validates that
   `GlobalConfig.model_validate({"git": {"checkout_root": "/srv/repos"}})` produces
   `config.checkout_root == "/srv/repos"`.
2. `test_global_config_migrates_git_checkout_root_does_not_override_explicit` — validates
   that an explicit top-level `checkout_root` takes precedence over the legacy path.

All 6 `TestCheckoutRootRelocation` tests pass.

**Commit:** `3f5d90111`

---

## Verdict

```
REVIEW COMPLETE: config-independent-schemas

Critical: 0
Important: 0 (I-1 resolved: scope addendum added; I-2 resolved: migration tests added)
Suggestions: 1 (S-1: unresolved, acceptable under APPROVE)

Verdict: APPROVE
```
