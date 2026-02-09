# Implementation Plan: Person Identity Auth — Phase 1

## Objective

Build the identity model foundation consumed by all subsequent auth phases.

## Task 1: Human role constants

**File:** `teleclaude/constants.py`

Add constants:

```python
HUMAN_ROLE_ADMIN = "admin"
HUMAN_ROLE_MEMBER = "member"
HUMAN_ROLE_CONTRIBUTOR = "contributor"
HUMAN_ROLE_NEWCOMER = "newcomer"
HUMAN_ROLES = {HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER}
```

**Verification:** Import constants in test, confirm values.

## Task 2: IdentityContext and IdentityResolver

**File:** `teleclaude/core/identity.py` (new)

- `IdentityContext` dataclass with `email`, `role`, `username`, `resolution_source`.
- `IdentityResolver` class:
  - Constructor builds `_by_email` and `_by_username` lookup dicts from `list[PersonEntry]`.
  - `resolve_by_email()` and `resolve_by_username()` methods.
- Module-level `get_identity_resolver() -> IdentityResolver` that calls `load_global_config()` and constructs resolver from `global_config.people`.

**Verification:** Unit tests for all resolver paths.

## Task 3: Unit tests

**File:** `tests/unit/test_identity.py`

- PersonEntry parsing from dict (valid and invalid roles).
- IdentityResolver: email lookup → correct IdentityContext.
- IdentityResolver: username lookup → correct IdentityContext.
- IdentityResolver: unknown email → None.
- IdentityResolver: unknown username → None.
- IdentityContext construction with all field combinations.

## Files Changed

| File                          | Change                                  |
| ----------------------------- | --------------------------------------- |
| `teleclaude/constants.py`     | Add human role constants                |
| `teleclaude/core/identity.py` | New — IdentityContext, IdentityResolver |
| `tests/unit/test_identity.py` | New — unit tests                        |

## Risks

1. **Depends on config-schema-validation** — PersonEntry and load_global_config must exist. If not yet delivered, this todo is blocked.

## Verification

- All unit tests pass.
- IdentityResolver correctly resolves from sample people config.
- Invalid roles raise during config validation.
