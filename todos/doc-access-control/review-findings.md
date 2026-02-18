# Review Findings: doc-access-control

**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-18
**Round:** 2
**Verdict:** APPROVE

---

## Critical

(none)

## Important

### 1. `_load_index` defaults missing role to `"admin"` instead of `"member"`

**File:** `teleclaude/context_selector.py:239`

```python
role = raw_role if isinstance(raw_role, str) else "admin"
```

The `SnippetMeta` dataclass default (line 30) is also `"admin"`. Meanwhile, `docs_index.py:578` defaults to `DEFAULT_ROLE = "member"`. This inconsistency means legacy indexes (before `telec sync` adds `role` fields) would treat all snippets as admin-only, making them invisible to member sessions.

In practice this is **fail-closed** (too restrictive, not leaking content) and self-corrects after one `telec sync`. Not a security vulnerability, but a usability issue during migration.

**Fix:** Import `DEFAULT_ROLE` from `docs_index` and use it in both the dataclass default and the `_load_index` fallback:

```python
# context_selector.py line 30
from teleclaude.docs_index import DEFAULT_ROLE
role: str = DEFAULT_ROLE

# context_selector.py line 239
role = raw_role if isinstance(raw_role, str) else DEFAULT_ROLE
```

### 2. Unknown role values in `_include_snippet` bypass the filter

**File:** `teleclaude/context_selector.py:445-446`

```python
snippet_rank = ROLE_RANK.get(snippet.role)
if snippet_rank is not None and _role_rank < snippet_rank:
    return False
```

If `snippet.role` is a string not in `ROLE_RANK` (e.g., a typo like `"superadmin"` in a hand-edited index), `snippet_rank` is `None` and the entire role check is **skipped** — the snippet becomes visible to everyone including public sessions.

In practice this requires corrupted/hand-edited index data (the builder validates against `ROLE_RANK`), but the fix is one line:

```python
snippet_rank = ROLE_RANK.get(snippet.role, max(ROLE_RANK.values()))
```

This treats unknown role values as maximally restrictive (fail-closed).

## Suggestions

### 1. No unit tests for `_check_customer_guard()` (FR4)

FR4 (CLI config command gating) is the only requirement with zero direct test coverage. A single test mocking `$TMPDIR`, the session file, and `get_session_field_sync` would cover the three key paths (blocks customer, blocks public, allows member).

### 2. Narrow the `except Exception: pass` in `_check_customer_guard()`

**File:** `teleclaude/cli/config_cli.py:57-61`

The bare `except Exception: pass` is too broad. It catches `ImportError` (broken install), `ValueError` (field rename), and `TypeError` (config corruption) — all of which would silently disable CLI access control. Consider narrowing to `(OSError, sqlite3.OperationalError)` for the legitimate "DB unavailable" case and logging unexpected errors.

### 3. Access-denied notice could include role context

**File:** `teleclaude/context_selector.py:622-634`

The Phase 2 access-denied notice says "Insufficient role for current session" but doesn't specify the caller's role or the required role. Including both would help agents understand the denial.

### 4. Stale `audience` references in architecture doc

`docs/project/design/architecture/help-desk-platform.md` still uses the old `audience` terminology in several places. Not in this branch's scope (the file wasn't changed), but worth a follow-up cleanup.

---

## Requirements Verification

| Requirement                       | Status | Notes                                                               |
| --------------------------------- | ------ | ------------------------------------------------------------------- |
| FR1: `role` frontmatter field     | PASS   | Code reads `role`, docs updated, schema correct                     |
| FR2: Role hierarchy               | PASS   | Rank comparison: admin(2) > member(1) > public(0). No role → public |
| FR3: `get_context` role filtering | PASS   | Phase 1 index filtered. Phase 2 returns access-denied notice        |
| FR4: CLI config command gating    | PASS   | Mutating commands guarded for `customer` and `public` roles         |
| FR5: Gradual migration            | PASS   | Default `member` hides existing snippets from public                |

## Test Verification

All 37 branch-relevant tests pass:

- 4 role derivation tests (`test_context_index.py`)
- 8 role filtering tests (`test_context_selector.py`) including Phase 2 access denial
- 5 role filtering tests (`test_help_desk_features.py::TestRoleFiltering`)
- 2 bootstrap cleanup tests (`test_help_desk_features.py::TestBootstrapCleanup`)
- 18 pre-existing tests (identity, tool filtering, channel, relay, etc.)

20 pre-existing test failures in unrelated modules (TUI, daemon startup, command handlers) — not introduced by this branch.

## Round 1 Findings — Resolution Status

| Finding                                            | Status   |
| -------------------------------------------------- | -------- |
| 1. Docs say `clearance`, code reads `role`         | RESOLVED |
| 2. `audience` array replaced with `role` field     | RESOLVED |
| 3. CLI guard only checked `customer`, not `public` | RESOLVED |
| 4. No-role sessions defaulted to admin access      | RESOLVED |
| 5. Bootstrap cleanup missing                       | RESOLVED |
| 6. Bootstrap test called function with wrong sig   | RESOLVED |
| S1. Stale `audience` field in schema docs          | RESOLVED |

All round-1 findings resolved in commits `ada76a3d` and `7d87f967`.
