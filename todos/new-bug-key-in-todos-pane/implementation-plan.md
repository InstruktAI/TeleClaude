# Implementation Plan: new-bug-key-in-todos-pane

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `b` keybinding to TUI todos pane for quick bug creation, plus `telec bugs create` CLI command.

**Architecture:** Reuses `create_bug_skeleton()` from `bug-delivery-service`. The TUI flow mirrors the existing `n` → `action_new_todo()` → `CreateTodoModal` → scaffold → editor pattern, but targets `bug.md` instead of `input.md`.

**Prerequisite:** `bug-delivery-service` must be built first (provides `create_bug_skeleton()` and `templates/todos/bug.md`).

---

### Task 1: Add `telec bugs create` CLI Subcommand

**File(s):** `teleclaude/cli/telec.py`

**Steps:**

1. Add `create` subcommand to the existing `"bugs"` entry in `CLI_SURFACE` (created by `bug-delivery-service`):
   ```python
   "create": CommandDef(
       desc="Scaffold bug files for a slug",
       args="<slug>",
       flags=[_PROJECT_ROOT_LONG],
   ),
   ```
2. Add `_handle_bugs_create()` handler:
   - Parse slug from args.
   - Resolve project root.
   - Call `create_bug_skeleton(project_root, slug, description="")` with empty description (user fills in manually).
   - Print success message with path.
   - Handle `ValueError` and `FileExistsError` with clear error messages.
3. Wire the handler into `_handle_bugs()` router.

**Verification:** `telec bugs create test-bug` creates `todos/test-bug/bug.md` + `state.yaml`. Clean up after.

---

### Task 2: Add `b` Keybinding to TUI PreparationView

**File(s):** `teleclaude/cli/tui/views/preparation.py`

**Steps:**

1. Add keybinding to `BINDINGS` list:
   ```python
   ("b", "new_bug", "New bug"),
   ```
2. Add `action_new_bug()` method following the same pattern as `action_new_todo()`:
   - Push `CreateBugModal()` screen (see Task 3).
   - On result, resolve project root from `_slug_to_project_path`.
   - Call `create_bug_skeleton(Path(project_root), slug, description="")`.
   - Post `DocEditRequest` for `bug.md` instead of `input.md`:
     ```python
     DocEditRequest(
         doc_id=f"todo:{slug}:bug.md",
         command=self._editor_command(slug, "bug.md"),
         title=f"Editing: {slug}/bug.md",
     )
     ```
   - Handle `ValueError` and `FileExistsError` with `self.app.notify()`.

**Verification:** Press `b` in TUI → modal appears → enter slug → `bug.md` opens in editor.

---

### Task 3: Create or Adapt Bug Modal

**File(s):** `teleclaude/cli/tui/widgets/modals.py`

**Steps:**

1. Option A (preferred): Create `CreateBugModal` as a minimal variant of `CreateTodoModal`:
   - Same structure: slug input, validation, Enter/Esc.
   - Different title: "New Bug" instead of "New Todo".
   - Same `SLUG_PATTERN` validation.
2. Option B: Reuse `CreateTodoModal` directly (rename or parameterize). Only if the two are truly identical in behavior.

**Decision:** Option A is cleaner — the title distinction is user-facing and important for clarity. The class is small (~48 lines) so duplication cost is minimal.

**Verification:** Modal renders with "New Bug" title, validates slug, returns slug on Enter.

---

### Task 4: Validation

**Steps:**

- [ ] `make lint` passes.
- [ ] `make test` passes (existing tests unbroken).
- [ ] Manual TUI test: `b` → enter slug → bug.md opens.
- [ ] Manual CLI test: `telec bugs create test-slug` → creates correct files.
- [ ] Edge cases: empty slug, invalid slug, duplicate slug all show errors.
- [ ] `n` key still works for normal todos (no regression).

---

## Phase 2: Quality Checks

- [ ] Run `make lint`
- [ ] Run `make test`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Requirements reflected in code changes
- [ ] Implementation tasks all marked `[x]`
- [ ] Deferrals documented if applicable
