# Requirements: slug-helper

## Goal

Extract a shared slug helper module (`teleclaude/slug.py`) that consolidates scattered
slug validation, normalization, and uniqueness logic into a single source of truth.

## In Scope

- New module `teleclaude/slug.py` with three public functions:
  - `validate_slug(slug: str) -> None` — format check against `SLUG_PATTERN`, raises `ValueError`
  - `normalize_slug(text: str) -> str` — text-to-slug conversion (lowercase, strip non-alphanumeric to hyphens, collapse runs, strip edges)
  - `ensure_unique_slug(base_dir: Path, slug: str) -> str` — counter-suffix collision resolution (appends `-2`, `-3`, etc.)
- Re-export `SLUG_PATTERN` from the new module.
- Wire all existing callers to import from `teleclaude/slug.py`:
  - `teleclaude/todo_scaffold.py`: `create_todo_skeleton`, `create_bug_skeleton`, `remove_todo` — replace inline validation and `FileExistsError` collision behavior with `validate_slug` + `ensure_unique_slug`
  - `teleclaude/content_scaffold.py`: `_derive_slug` — replace with `normalize_slug`; inline counter-suffix logic in `create_content_inbox_entry` — replace with `ensure_unique_slug`
  - `teleclaude/cli/telec.py`: `_handle_bugs_report` — replace inline normalization with `normalize_slug`; `_handle_content_dump` — replace inline normalization with `normalize_slug`
  - `teleclaude/cli/tui/widgets/modals.py`: `CreateTodoModal._do_create` — import `SLUG_PATTERN` from `teleclaude.slug` instead of `teleclaude.todo_scaffold`
- Update existing tests to import from `teleclaude.slug` and cover the new functions.

## Out of Scope

- `teleclaude/core/integration/blocked_followup.py`: its `_normalize_slug` is private and domain-specific (integration follow-up slugs have different constraints). Leave it untouched.
- `teleclaude/core/roadmap.py`: `slugify_heading` is a local helper inside `load_todos()` with different semantics (heading-to-slug, not user-input-to-slug). Leave it untouched.
- Changing the slug format rules themselves (the regex stays the same).
- Adding new CLI flags or commands.

## Success Criteria

- [ ] `SLUG_PATTERN`, `validate_slug`, `normalize_slug`, `ensure_unique_slug` are importable from `teleclaude.slug`
- [ ] All callers listed above import from `teleclaude.slug` instead of duplicating logic
- [ ] No duplicate slug validation regex or normalization logic remains in `todo_scaffold.py`, `content_scaffold.py`, or `telec.py`
- [ ] `create_todo_skeleton` and `create_bug_skeleton` use `ensure_unique_slug` instead of raising `FileExistsError` on collision (behavior change: counter-suffix instead of hard error)
- [ ] Existing tests pass after rewiring imports
- [ ] New unit tests cover `validate_slug`, `normalize_slug`, `ensure_unique_slug` edge cases
- [ ] `make test` and `make lint` pass

## Constraints

- The `SLUG_PATTERN` regex must not change: `^[a-z0-9]+(?:-[a-z0-9]+)*$`
- `normalize_slug` must handle the `_derive_slug` use case (first-N-words extraction with fallback) — either as a parameter or as a thin wrapper in `content_scaffold.py` that calls `normalize_slug` for the character-level work
- `ensure_unique_slug` must be filesystem-based (check directory existence), not database-based
- The `_derive_slug` word-extraction logic (take first 5 meaningful words, skip single-char words, fallback to "dump") may remain as a thin caller-side wrapper around `normalize_slug` if that keeps the module focused on slug mechanics rather than content-domain semantics

## Risks

- Callers that currently catch `FileExistsError` from `create_todo_skeleton`/`create_bug_skeleton` will need updating since those functions will no longer raise it (they'll return a unique slug instead). Callers: `telec.py` lines 2109, 2247, 2767, 2822; `preparation.py` lines 776, 785.
- **Caller slug desync**: callers that use the original `slug` variable after calling skeleton functions must update to use `todo_dir.name` instead, since `ensure_unique_slug` may have suffixed the slug. Affected: `telec.py:2829` (git branch), `telec.py:2253` (print), `preparation.py:790` (filepath construction).
