# Review Findings: db-raw-sql-cleanup

## Critical

- None.

## Important

1. Raw-SQL marker contract drift from requirements and plan
   - `todos/db-raw-sql-cleanup/requirements.md` and `todos/db-raw-sql-cleanup/implementation-plan.md` specify `# noqa: raw-sql`, but the implementation switched to `# allow: raw-sql` in `teleclaude/core/db.py:173`, `teleclaude/core/db.py:237`, `teleclaude/core/db.py:1296`, `teleclaude/hooks/receiver.py:64`, and `scripts/check-raw-sql.sh:22`.
   - This fails the stated acceptance criterion and leaves the work item internally inconsistent (the hook name in `.pre-commit-config.yaml:45` still says "without noqa markers").
   - Fix: either revert to `# noqa: raw-sql` in code/script, or update requirements/plan/hook messaging to the new marker contract in the same change.

2. Contract violation is silently converted into "not found"
   - `_fetch_session_id_sync` now does `getattr(db_models.Session, field, None)` and returns `None` for invalid fields (`teleclaude/core/db.py:1305`).
   - Concrete failure path: `get_session_id_by_field_sync(db_path, "tmux_session_nam", "x")` now returns `None` (indistinguishable from a real miss) instead of surfacing an invalid field bug.
   - This violates fail-fast policy for contract errors and can hide typos/misconfiguration in standalone callers.
   - Fix: validate `field` against an explicit allowlist and raise `ValueError` for invalid names; add a unit test for the invalid-field path.

## Suggestions

1. Add a focused test that asserts invalid `field` raises an explicit error for `get_session_id_by_field_sync`.
2. Normalize naming in `.pre-commit-config.yaml:45` ("noqa markers" vs current "allow: raw-sql") to avoid future reviewer confusion.

## Verdict

REQUEST CHANGES
