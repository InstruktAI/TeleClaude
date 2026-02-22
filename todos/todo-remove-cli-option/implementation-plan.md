# Implementation Plan: todo-remove-cli-option

## Overview

Add todo removal capability via CLI and TUI. The approach follows established patterns: `todo_scaffold.py` for core logic (matching `create_todo_skeleton`), `telec.py` for CLI routing (matching `_handle_todo_create`), and `preparation.py` for TUI keybinding (matching `action_new_todo`). The filesystem watcher already emits `todo_removed` events, so the TUI refreshes automatically.

## Phase 1: Core Logic

### Task 1.1: Add `remove_todo` to `todo_scaffold.py`

**File(s):** `teleclaude/todo_scaffold.py`

- [x] Add `remove_todo(project_root: Path, slug: str) -> None` function
- [x] Validate slug format using existing `SLUG_PATTERN`
- [x] Guard: check if `trees/{slug}/` worktree exists; raise `RuntimeError` if so
- [x] Remove entry from `roadmap.yaml` via `remove_from_roadmap()`
- [x] Remove entry from `icebox.yaml` if present (load, filter, save)
- [x] Clean up `after` references: iterate remaining roadmap entries and icebox entries, remove the slug from any `after` lists, save if changed
- [x] Delete `todos/{slug}/` directory via `shutil.rmtree()` if it exists
- [x] Raise `FileNotFoundError` if slug has no directory and no roadmap/icebox entry

### Task 1.2: Add icebox removal helper to `core/next_machine/core.py`

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Add `remove_from_icebox(cwd: str, slug: str) -> bool` function (mirrors `remove_from_roadmap`)
- [x] Add `clean_dependency_references(cwd: str, slug: str) -> None` to strip a slug from all `after` lists in both roadmap and icebox

---

## Phase 2: CLI Integration

### Task 2.1: Add `remove` to CLI_SURFACE schema

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `"remove"` subcommand to `CLI_SURFACE["todo"].subcommands` with args `"<slug>"`, flags `[_PROJECT_ROOT_LONG]`, and desc `"Remove a todo and its files"`

### Task 2.2: Add `_handle_todo_remove` function

**File(s):** `teleclaude/cli/telec.py`

- [x] Implement `_handle_todo_remove(args: list[str]) -> None` following `_handle_todo_create` pattern
- [x] Parse `<slug>` and optional `--project-root`
- [x] Call `remove_todo()` from `todo_scaffold`
- [x] Print success message or error (FileNotFoundError, RuntimeError for worktree)

### Task 2.3: Wire into `_handle_todo` router

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `elif subcommand == "remove":` branch calling `_handle_todo_remove(args[1:])`

---

## Phase 3: TUI Integration

### Task 3.1: Add `R` keybinding to PreparationView

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [x] Add `("R", "remove_todo", "Remove")` to `BINDINGS` list (capital R, matching sessions view `R` for restart)

### Task 3.2: Implement `action_remove_todo` method

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [x] Resolve slug from current todo row or parent of current file row
- [x] Resolve project root from `_slug_to_project_path`
- [x] Show `ConfirmModal` with title "Remove Todo" and message "Remove todo '{slug}' and all its files?"
- [x] On confirm, call `remove_todo()` from `todo_scaffold`
- [x] On success, show `self.app.notify(f"Removed {slug}")` notification
- [x] On error (worktree exists), show `self.app.notify(str(exc), severity="error")`
- [x] No manual refresh needed — `TodoWatcher` handles it via filesystem events

---

## Phase 4: Validation

### Task 4.1: Unit Tests

**File(s):** `tests/unit/test_todo_scaffold.py`

- [ ] Test `remove_todo` with a normal slug: directory deleted, roadmap entry removed
- [ ] Test `remove_todo` with an icebox slug: directory deleted, icebox entry removed
- [ ] Test `remove_todo` when slug has dependents: `after` references cleaned up
- [ ] Test `remove_todo` when worktree exists: raises `RuntimeError`
- [ ] Test `remove_todo` when slug not found anywhere: raises `FileNotFoundError`

### Task 4.2: CLI Tests

**File(s):** `tests/unit/test_telec_todo_cli.py`

- [ ] Test `telec todo remove <slug>` success path
- [ ] Test `telec todo remove` without slug shows usage

### Task 4.3: Quality Checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify TUI refresh works after removal (manual check via `pkill -SIGUSR2`)

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
