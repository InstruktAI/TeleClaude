# Implementation Plan: mark-phase-force

## Overview

Three targeted changes to `todo_routes.py` plus one to the CLI. No new modules, no new
artifact checks. Guards are removed or narrowed in-place; `--force` wraps what stays.

---

## [x] Task 1: Add `force` parameter and rewrite build/review guard block

**File:** `teleclaude/api/todo_routes.py`

**Why:** All three guard changes (flexible cwd, stash removal, narrowed uncommitted) live
in the same build/review block. Doing them together avoids reading the state twice.

**What to change:**

1. Add `force: Annotated[bool, Body()] = False` to `todo_mark_phase` signature.

2. Replace the build/review guard block:

```python
# BEFORE (simplified)
worktree_cwd = str(Path(cwd) / WORKTREE_DIR / slug)
if not Path(worktree_cwd).exists():
    raise HTTPException(status_code=404, ...)
terminal_statuses = ("complete", "approved")
if status in terminal_statuses:
    if has_uncommitted_changes(cwd, slug):
        raise HTTPException(...)
    stash_entries = get_stash_entries(cwd)
    if stash_entries:
        raise HTTPException(...)
updated_state = mark_phase(worktree_cwd, slug, phase, status)

# AFTER
worktree_path = Path(cwd) / WORKTREE_DIR / slug
if worktree_path.exists():
    effective_cwd = str(worktree_path)
elif force:
    effective_cwd = cwd
else:
    raise HTTPException(status_code=404, detail=f"worktree not found at {worktree_path}")

build_terminal = ("complete", "approved")
if not force and phase == PhaseName.BUILD.value and status in build_terminal:
    if has_uncommitted_changes(cwd, slug):
        raise HTTPException(status_code=409, detail=...)

# stash check removed entirely

updated_state = mark_phase(effective_cwd, slug, phase, status)
```

3. Remove `get_stash_entries` from the import block (verify it is not used elsewhere in
   this file before removing).

4. Add `PhaseName` to imports from `teleclaude.core.next_machine._types` if not already
   present (needed for `phase == PhaseName.BUILD.value` comparison).

**Test spec (write as `@pytest.mark.xfail` first):**

```python
@pytest.mark.xfail(reason="mark-phase-force not implemented")
async def test_mark_phase_build_complete_force_skips_uncommitted_check(): ...

@pytest.mark.xfail(reason="mark-phase-force not implemented")
async def test_mark_phase_review_approved_no_longer_blocks_on_uncommitted(): ...

@pytest.mark.xfail(reason="mark-phase-force not implemented")
async def test_mark_phase_stash_no_longer_blocks_any_phase(): ...

@pytest.mark.xfail(reason="mark-phase-force not implemented")
async def test_mark_phase_force_falls_back_to_cwd_when_no_worktree(): ...

@pytest.mark.xfail(reason="mark-phase-force not implemented")
async def test_mark_phase_no_force_still_404_when_worktree_absent(): ...
```

**Verification:** All five xfail tests GREEN. Existing test asserting stash blocks updated
(stash no longer blocks — test updated, not deleted).

---

## [x] Task 2: CLI — add `--force` flag

**File:** `teleclaude/cli/tool_commands/todo.py`

**Why:** Agents and humans need `--force` from the shell.

**What to change:**

In the arg-parse loop, add:

```python
elif arg == "--force":
    body["force"] = True
```

Update docstring:

```
--force          Bypass worktree, uncommitted-changes, and stash guards

Examples:
  telec todo mark-phase my-slug --phase build --status pending --force
  telec todo mark-phase my-slug --phase review --status approved --force
```

**Test spec:**

```python
@pytest.mark.xfail(reason="mark-phase-force not implemented")
def test_handle_mark_phase_passes_force_flag(): ...
```

**Verification:** xfail test GREEN.

---

## [x] Task 3: Finalize — remove xfail markers, run checks

Remove all `@pytest.mark.xfail` markers as implementations land. Run `make test` and
`make lint`. Verify `get_stash_entries` is not imported in routes file after removal.

---

## [x] Task 4: Expand TodoState with full canonical schema

**File:** `teleclaude/types/todos.py`

Add all state fields (phase, finalize, grounding, reviews, artifacts, audit) as Pydantic
sub-models. `schema_version` defaults to 1 — this IS the only schema.

---

## [x] Task 5: Replace DEFAULT_STATE dict with default_state() function

**Files:** `teleclaude/core/next_machine/_types.py`, `state_io.py`, `prepare_events.py`,
`prepare_steps.py`, `core.py`, `todo_scaffold.py`, `scripts/diagrams/extract_state_machines.py`

Delete the hardcoded DEFAULT_STATE dict. All consumers call `default_state()` which
delegates to `TodoState().model_dump()`. Scaffold simplified to use TodoState defaults.

---

## [x] Task 6: Remove v1/v2 compat code

**Files:** `prepare_events.py`, `state_io.py`, `delivery.py`, `prepare_steps.py`, `core.py`

Rename `_is_artifact_produced_v2` → `_is_artifact_produced`, remove `schema_version < 2`
early return. Remove `state.json` fallback paths. Clean stale v1/v2 comments.

---

## [x] Task 7: Migrate existing state.yaml files

Round-trip all 41 `todos/*/state.yaml` files through `TodoState` to fill missing fields,
normalize nulls to empty strings, and set `schema_version: 1` everywhere.

---

## Referenced Files

- `teleclaude/api/todo_routes.py`
- `teleclaude/cli/tool_commands/todo.py`
- `teleclaude/types/todos.py`
- `teleclaude/core/next_machine/_types.py`
- `teleclaude/core/next_machine/core.py`
- `teleclaude/core/next_machine/state_io.py`
- `teleclaude/core/next_machine/prepare_events.py`
- `teleclaude/core/next_machine/prepare_steps.py`
- `teleclaude/core/next_machine/delivery.py`
- `teleclaude/todo_scaffold.py`
- `scripts/diagrams/extract_state_machines.py`
- `tests/unit/api/test_todo_routes.py`
- `tests/unit/cli/tool_commands/test_todo.py`
