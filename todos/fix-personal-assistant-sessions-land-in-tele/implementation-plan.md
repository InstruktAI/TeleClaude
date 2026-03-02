# Implementation Plan: Personal Assistant Sessions Landing Path

## Objective

Remove unnecessary `workspace/` subfolder from personal assistant session paths. Sessions should land directly in `~/.teleclaude/people/{name}/` instead of `~/.teleclaude/people/{name}/workspace/`.

## Analysis

**Current Problem:** `scaffold_personal_workspace()` in `teleclaude/invite.py` creates and returns a `workspace/` subdirectory, causing all personal assistant sessions to land in the wrong location. The person's folder IS the workspace—there is no need for extra indirection.

**Impact:** All personal assistant sessions initiated via Telegram and Discord adapters land in the wrong directory path.

## Solution Design

Modify `scaffold_personal_workspace()` to:
1. Return `_PEOPLE_DIR / person_name` directly (the person's folder)
2. Remove the `workspace/` subfolder construction
3. Remove symlink/copy logic for `AGENTS.master.md` (file already lives in person folder)
4. Keep `teleclaude.yml` creation targeting the person folder directly
5. Add fallback for missing `AGENTS.master.md` with sensible default

**No caller changes needed:** All four call sites in `telegram_adapter.py` and `discord_adapter.py` already use the returned path as `project_path` without further manipulation.

## Implementation Steps

1. **Refactor `scaffold_personal_workspace()`** — Update function to return person folder directly
   - Remove workspace subfolder path construction
   - Simplify file creation logic
   - Add documentation clarifying return path

2. **Add test coverage** — Create `tests/unit/test_invite_scaffold.py` with comprehensive tests:
   - Return path is person folder, not workspace subfolder
   - Person folder is created if absent
   - Default `AGENTS.master.md` is created only if absent
   - Existing `AGENTS.master.md` is not overwritten
   - `teleclaude.yml` is created in person folder
   - No `workspace/` subfolder is created

3. **Verify callers** — Confirm all four call sites work correctly without modification

## Testing Strategy

- **Unit tests:** 6 new tests covering all scenarios in `test_invite_scaffold.py`
- **Integration:** Verify existing test suite passes (2468 total unit tests)
- **Manual verification:** Confirm session paths are correct after deployment

## Success Criteria

- ✓ `scaffold_personal_workspace()` returns person folder directly
- ✓ No `workspace/` subfolder is created
- ✓ All 6 new tests pass
- ✓ All 2468 existing unit tests pass
- ✓ No changes needed to caller code
