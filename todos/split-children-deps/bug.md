# Bug: telec todo split creates children with after:[parent] dependency instead of group:[parent], making children depend on their own container completing first. Also, scaffolded input.md files are empty templates requiring manual read+write to seed — should either accept --seed-from or copy parent context automatically.

## Symptom

telec todo split creates children with after:[parent] dependency instead of group:[parent], making children depend on their own container completing first. Also, scaffolded input.md files are empty templates requiring manual read+write to seed — should either accept --seed-from or copy parent context automatically.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-11

## Investigation

`teleclaude/todo_scaffold.py` `split_todo()` calls `create_todo_skeleton()` with `after=[parent_slug]`,
which registers children in the roadmap with an `after` dependency (sequential gate) instead of a
`group` membership. `create_todo_skeleton` had no `group` parameter and no way to seed `input.md`
with parent context.

## Root Cause

Two independent defects in `split_todo` / `create_todo_skeleton`:

1. **Wrong dependency kind:** `split_todo` passed `after=[parent_slug]` to `create_todo_skeleton`,
   which forwarded it as `after=` to `add_to_roadmap`. Children became sequentially blocked on the
   parent completing rather than being grouped under it.

2. **Empty input.md:** `create_todo_skeleton` always wrote the blank `input.md` template.
   `split_todo` never copied the parent's accumulated context, so each child started cold.

## Fix Applied

`teleclaude/todo_scaffold.py`:

- Added `group: str | None = None` and `seed_input: str | None = None` parameters to
  `create_todo_skeleton`. The `group` value is forwarded to `add_to_roadmap`; `seed_input`
  replaces the blank template when provided.
- `split_todo` now reads the parent's `input.md` before scaffolding children, then calls
  `create_todo_skeleton(project_root, child, group=parent_slug, seed_input=parent_input_content)`
  for each child.
