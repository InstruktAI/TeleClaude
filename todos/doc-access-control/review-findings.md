# Review Findings: doc-access-control

**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-18
**Round:** 1
**Verdict:** REQUEST CHANGES

---

## Critical

(none)

## Important

### 1. Documentation says `clearance`, code reads `role`

The code (`docs_index.py:574`, `resource_validation.py:349,560`, `context_selector.py`) reads `metadata.get("role")` from snippet frontmatter. However, four documentation files still instruct authors to use `clearance`:

- `docs/global/general/procedure/doc-snippet-authoring.md:30` — "Set `clearance` if the snippet should be restricted"
- `docs/global/general/spec/snippet-authoring-schema.md:25-26,65` — documents `clearance` and `audience` fields
- `docs/global/general/spec/tools/memory-management-api.md:6` — has `clearance: 'admin'` in frontmatter
- `todos/roadmap.md:30` — "Role-based `clearance` frontmatter"

**Impact:** The one tagged snippet (`memory-management-api.md`) has `clearance: 'admin'` which the code ignores. It gets indexed as `role: member` (the default) instead of `role: admin`, meaning member-level callers can see admin-only content. Any future snippets authored per the current docs will have the same problem.

**Fix:** Rename `clearance` to `role` in all four files. Remove the `audience` reference from `snippet-authoring-schema.md` (audience was fully replaced by role).

### 2. [FIXED in prior round] Replaced `audience` array with `role` field

The original build used `CLEARANCE_TO_AUDIENCE` with set-intersection filtering. Replaced with a single `role` field and rank comparison.

### 3. [FIXED in prior round] CLI guard only checked `customer`, not `public`

Updated to `if role in ("customer", "public")`.

### 4. [FIXED in prior round] No-role sessions defaulted to admin access

Fixed to default to `public` (least privilege).

### 5. [FIXED in prior round] Bootstrap cleanup missing

Added try/except with `shutil.rmtree` on failure.

### 6. [FIXED in prior round] Bootstrap test called function with wrong signature

Fixed call sites.

## Suggestions

### 1. Remove stale `audience` field from schema docs

`snippet-authoring-schema.md:26` still documents an `audience` array field that no longer exists in the codebase. Should be removed entirely along with the "Prefer `clearance` over `audience`" guidance on line 25.

### 2. Rename `HUMAN_ROLE_CUSTOMER` to `HUMAN_ROLE_PUBLIC`

`teleclaude/constants.py` still defines `HUMAN_ROLE_CUSTOMER = "customer"`. The decided role name is `public`. Out of scope — requires DB schema change.

### 3. Rename `human_role` to `role` on session model

The session field is still `human_role`. Should be just `role`. Separate refactor with DB migration.

---

## Requirements Verification

| Requirement                       | Status | Notes                                                                    |
| --------------------------------- | ------ | ------------------------------------------------------------------------ |
| FR1: `role` frontmatter field     | FAIL   | Code correct, but docs instruct authors to use `clearance` instead.      |
| FR2: Role hierarchy               | PASS   | Rank comparison: admin(2) > member(1) > public(0). No role -> public.    |
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

## Fixes Applied This Round (Round 2)

### Important Issue 1 — Documentation says `clearance`, code reads `role`

**Commit:** `7d87f967`

- `docs/global/general/procedure/doc-snippet-authoring.md`: step 3 — `clearance` → `role`
- `docs/global/general/spec/snippet-authoring-schema.md`: replaced `clearance` + `audience` fields with single `role` field; updated Allowed values section
- `docs/global/general/spec/tools/memory-management-api.md`: frontmatter `clearance: 'admin'` → `role: admin`
- `todos/roadmap.md`: description updated to `role` frontmatter

Suggestion 1 (stale `audience` field) addressed in the same commit.

---

## Fixes Applied During Prior Review Round

1. `teleclaude/docs_index.py` — replaced `CLEARANCE_TO_AUDIENCE` with `ROLE_RANK`
2. `teleclaude/context_selector.py` — replaced `audience` tuple with `role` string, rank comparison
3. `teleclaude/constants.py` — `ROLE_VALUES` replaces `AUDIENCE_VALUES`
4. `teleclaude/resource_validation.py` — validates `role` field instead of `audience`
5. `teleclaude/cli/config_cli.py` — error message updated
6. `teleclaude/project_setup/help_desk_bootstrap.py` — added cleanup on failure
7. All test files updated to use `role` field in fixtures
8. All todo docs updated to use `role` terminology
