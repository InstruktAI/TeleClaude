# Review Findings: doc-access-control

**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-18
**Verdict:** APPROVE

---

## Critical

(none)

## Important

### 1. [FIXED] Replaced `audience` array with `role` field

The original build used an `audience` array expansion (`CLEARANCE_TO_AUDIENCE`) with set-intersection filtering. Replaced with a single `role` field and rank comparison. Simpler, no intermediate concepts.

### 2. [FIXED] CLI guard only checked `customer`, not `public`

`_check_customer_guard()` only checked `if role == "customer"`. Updated to `if role in ("customer", "public")`.

### 3. [FIXED] Roadmap used stale terminology

`todos/roadmap.md` described levels as `public`/`internal`/`ops`/`admin`. Updated to `public`/`member`/`admin`.

### 4. [FIXED] No-role sessions defaulted to admin access

When `human_role` was `None`, the filter gave max rank (admin). Fixed to default to `public` (least privilege). Admin access must be explicit.

### 5. [FIXED] Bootstrap cleanup missing

`bootstrap_help_desk()` had no try/except around git operations. A failed git commit left a partial directory behind. Added cleanup on failure.

### 6. [FIXED] Bootstrap test called function with wrong signature

Two tests passed a positional argument to `bootstrap_help_desk()` which takes no arguments. Fixed call sites.

## Suggestions

### 1. Rename `HUMAN_ROLE_CUSTOMER` to `HUMAN_ROLE_PUBLIC`

`teleclaude/constants.py` still defines `HUMAN_ROLE_CUSTOMER = "customer"`. The decided role name is `public`. This rename affects the DB schema — out of scope, tracked as follow-up.

### 2. Rename `human_role` to `role` on session model

The session field is still `human_role`. Should be just `role`. Separate refactor with DB migration.

---

## Requirements Verification

| Requirement                       | Status | Notes                                                                    |
| --------------------------------- | ------ | ------------------------------------------------------------------------ |
| FR1: `role` frontmatter field     | PASS   | Three levels (`public`, `member`, `admin`). Default `member`.            |
| FR2: Role hierarchy               | PASS   | Rank comparison: admin(2) > member(1) > public(0). No role → public.     |
| FR3: `get_context` role filtering | PASS   | Phase 1 index filtered. Phase 2 returns access-denied notice.            |
| FR4: CLI config command gating    | PASS   | Mutating commands guarded for `customer` and `public` roles.             |
| FR5: Gradual migration            | PASS   | Default `member` hides existing snippets from public. No bulk retagging. |

## Test Verification

All 37 tests pass:

- 4 role derivation tests (`test_context_index.py`)
- 8 role filtering tests (`test_context_selector.py`) including Phase 2 access denial
- 5 role filtering tests (`test_help_desk_features.py::TestRoleFiltering`)
- 2 bootstrap cleanup tests (`test_help_desk_features.py::TestBootstrapCleanup`)
- 18 pre-existing tests (identity, tool filtering, channel, relay, etc.)

## Fixes Applied During Review

1. `teleclaude/docs_index.py` — replaced `CLEARANCE_TO_AUDIENCE` with `ROLE_RANK`
2. `teleclaude/context_selector.py` — replaced `audience` tuple with `role` string, rank comparison
3. `teleclaude/constants.py` — `ROLE_VALUES` replaces `AUDIENCE_VALUES`
4. `teleclaude/resource_validation.py` — validates `role` field instead of `audience`
5. `teleclaude/cli/config_cli.py` — error message updated
6. `teleclaude/project_setup/help_desk_bootstrap.py` — added cleanup on failure
7. All test files updated to use `role` field in fixtures
8. All todo docs updated to use `role` terminology
