# Implementation Plan: slug-helper

## Overview

Create `teleclaude/slug.py` as the single source of truth for slug operations,
then rewire all callers. The approach is bottom-up: build the module first, then
replace inline logic in each caller one at a time, verifying tests after each change.

## Phase 1: Core Module

### Task 1.1: Create `teleclaude/slug.py`

**File(s):** `teleclaude/slug.py`

- [x] Move `SLUG_PATTERN` from `todo_scaffold.py`
- [x] Implement `validate_slug(slug: str) -> None` — strips, checks empty, checks pattern, raises `ValueError`
- [x] Implement `normalize_slug(text: str) -> str` — lowercase, replace `[^a-z0-9-]+` with `-`, collapse `-+`, strip edges
- [x] Implement `ensure_unique_slug(base_dir: Path, slug: str) -> str` — if `base_dir/slug` exists, try `slug-2`, `slug-3`, etc. Return first non-existing

### Task 1.2: Unit tests for `teleclaude/slug.py`

**File(s):** `tests/unit/test_slug.py`

- [x] Test `validate_slug` accepts valid slugs, rejects invalid (uppercase, underscores, leading/trailing dash, empty)
- [x] Test `normalize_slug` with phrases, punctuation, mixed case, empty string
- [x] Test `ensure_unique_slug` with no collision, single collision, multiple collisions
- [x] Test `SLUG_PATTERN` is re-exported correctly

---

## Phase 2: Wire Callers

### Task 2.1: Update `todo_scaffold.py`

**File(s):** `teleclaude/todo_scaffold.py`

- [x] Import `validate_slug`, `ensure_unique_slug` from `teleclaude.slug`
- [x] Remove `SLUG_PATTERN` definition and `import re`
- [x] Re-export `SLUG_PATTERN` from `teleclaude.slug` for backward compatibility during transition (thin alias: `from teleclaude.slug import SLUG_PATTERN`)
- [x] In `create_todo_skeleton`: replace inline validation with `validate_slug(slug)`, replace `FileExistsError` with `slug = ensure_unique_slug(todos_root, slug)` before `mkdir`
- [x] In `create_bug_skeleton`: same pattern
- [x] In `remove_todo`: replace inline validation with `validate_slug(slug)`

### Task 2.2: Update `content_scaffold.py`

**File(s):** `teleclaude/content_scaffold.py`

- [x] Import `normalize_slug`, `ensure_unique_slug` from `teleclaude.slug`
- [x] Replace `_derive_slug` body: keep the word-extraction logic (first 5 words, skip single-char, fallback "dump") but call `normalize_slug` for the character-level conversion instead of inline regex
- [x] In `create_content_inbox_entry`: replace inline counter-suffix loop with `folder_name = ensure_unique_slug(inbox_dir, folder_name)`

### Task 2.3: Update `telec.py` CLI handlers and `preparation.py`

**File(s):** `teleclaude/cli/telec.py`, `teleclaude/cli/tui/views/preparation.py`

- [x] In `_handle_bugs_report`: replace inline `re.sub` normalization with `normalize_slug` import; remove `import re` if no longer needed
- [x] In `_handle_content_dump`: replace inline `re.sub` normalization with `normalize_slug` import; remove `import re` if no longer needed
- [x] Update `FileExistsError` catch blocks in `_handle_todo_create`, `_handle_bugs_report`, `_handle_bugs_create`, and TUI `preparation.py` — remove `FileExistsError` from except clauses since `create_todo_skeleton`/`create_bug_skeleton` no longer raise it
- [x] Fix caller slug desync: after `create_todo_skeleton`/`create_bug_skeleton` calls, derive the actual slug from the returned path (`slug = todo_dir.name`) before using `slug` in subsequent operations (git branch at `telec.py:2829`, print at `telec.py:2253`, filepath construction at `preparation.py:790`)

### Task 2.4: Update `modals.py`

**File(s):** `teleclaude/cli/tui/widgets/modals.py`

- [x] Change `from teleclaude.todo_scaffold import SLUG_PATTERN` to `from teleclaude.slug import SLUG_PATTERN`

---

## Phase 3: Test Migration

### Task 3.1: Update existing test imports

**File(s):** `tests/unit/cli/tui/test_create_todo_modal.py`, `tests/unit/test_todo_scaffold.py`, `tests/unit/test_content_scaffold.py`

- [x] `test_create_todo_modal.py`: change `SLUG_PATTERN` import to `teleclaude.slug`
- [x] `test_todo_scaffold.py`: update `FileExistsError` test — verify counter-suffix behavior instead
- [x] `test_content_scaffold.py`: keep `_derive_slug` tests but verify they still pass with the refactored implementation

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Run `make test` — all pass
- [x] Run `make lint` — all pass

### Task 4.2: Quality Checks

- [x] No duplicate `SLUG_PATTERN` definitions remain (only in `slug.py`, re-exported from `todo_scaffold.py`)
- [x] No inline slug normalization regex remains in `telec.py`
- [x] `grep -r "re.sub.*a-z0-9" teleclaude/` returns only `slug.py` and excluded files (`blocked_followup.py`, `roadmap.py`)
  - Note: `content_scaffold.py` retains `re.sub(r"[^a-z0-9\s]+", " ", lowered)` in `_derive_slug` for word-tokenization (not slug normalization); intentional per requirements.
