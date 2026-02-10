# Implementation Plan: Eliminate Raw SQL from DB Layer

## Objective

Convert remaining sync helper raw SQL to SQLModel and add pre-commit enforcement.

## Task 1: Convert sync helpers

**File:** `teleclaude/core/db.py`

Replace `_field_query()` f-string SQL and `_fetch_session_id_sync()` raw text() execution with SQLModel `select()`:

[x] Convert `_fetch_session_id_sync` to SQLModel.
[x] Consolidate `_field_query` into `_fetch_session_id_sync`.
[x] Update `get_session_id_by_field_sync` and `get_session_id_by_tmux_name_sync`.

**Verification:** Existing tests pass. Sync lookups return correct session IDs.

## Task 2: Pre-commit hook

**File:** New script or hook entry in `.pre-commit-config.yaml`

Add hook that greps for `text(` or `from sqlalchemy import text` in `teleclaude/core/db.py` and fails if any match lacks `# noqa: raw-sql` on the same line.

[x] Verify `scripts/check-raw-sql.sh` existence and functionality.
[x] Verify hook entry in `.pre-commit-config.yaml`.
[x] Test hook with unmarked raw SQL (confirmed failure).

**Verification:** Commit with unmarked raw SQL fails. Commit with marked PRAGMAs passes.

## Files Changed

| File                      | Change                           |
| ------------------------- | -------------------------------- |
| `teleclaude/core/db.py`   | Convert sync helpers to SQLModel |
| `.pre-commit-config.yaml` | Add raw SQL enforcement hook     |

## Risks

1. Sync helpers are used by standalone scripts (hook receiver, telec) that run outside the async daemon. SQLModel sync session must work in this context — verified by existing pattern in `_fetch_session_id_sync`.

## Verification

- All tests pass.
- Sync helpers return correct results.
- Pre-commit hook catches unmarked raw SQL.
