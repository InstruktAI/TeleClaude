# Implementation Plan: remove-phase-field

## Overview

Remove the `phase` field from `state.yaml` by replacing all reads/writes with equivalent `build`-based logic. The mapping is:

- `phase == pending` → `build == pending`
- `phase == in_progress` → `build != pending` (i.e. `started` or `complete`)
- `phase == done` → dead code (finalize removes from roadmap; never written)

The claim/lock point moves from `set_item_phase(... "in_progress")` to the existing `mark_phase(... "build", "started")` call 5 lines later, collapsing two operations into one.

## Phase 1: Core Changes

### Task 1.1: Remove `ItemPhase` enum and phase functions

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Remove `ItemPhase` enum (lines 50-53)
- [x] Remove `get_item_phase()` function (lines 616-628)
- [x] Remove `set_item_phase()` function (lines 644-654)
- [x] Remove `phase` from `DEFAULT_STATE` dict (line 308)
- [x] Remove `phase` migration code in `read_phase_state()` (lines 347-356)

### Task 1.2: Replace phase checks in `_find_next_prepare_slug()`

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Line 278/281: Replace `get_item_phase()` + `phase == DONE` skip with: check if slug not in roadmap (already handled by iteration) or `build == complete` AND `review == approved`
- [x] Line 295: Replace `phase == PENDING` check with `build == pending`

### Task 1.3: Replace phase checks in `resolve_slug()`

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Line 563/570: Replace `get_item_phase()` + `phase == DONE` skip. Use `read_phase_state()` and check `build`/`review` instead
- [x] Line 573: Replace `phase == IN_PROGRESS` check with `build != pending`

### Task 1.4: Replace phase checks in `is_ready_for_work()`

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Line 634-635: Replace `phase != PENDING` early return with `build != pending` early return (if build has started, item is not "ready for work")

### Task 1.5: Replace phase checks in `check_dependencies_satisfied()`

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Lines 838-839: Replace `get_item_phase()` + `phase != DONE` with: read state and check `review == approved` (the actual completion signal). Keep the "not in roadmap = satisfied" fallback (line 834-836) unchanged.

### Task 1.6: Replace phase in `next_work()` dispatch flow

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Line 2000: Replace `get_item_phase(... locked_slug) == DONE` with equivalent check (review approved or not in roadmap)
- [x] Lines 2027-2028: Replace `phase == PENDING and not is_ready_for_work` with `build == pending and not is_ready_for_work`
- [x] Line 2034: Replace `phase == DONE` check with review-approved or not-in-roadmap check
- [x] Lines 2117-2119: **Remove** the `set_item_phase(... IN_PROGRESS)` call. The claim/lock is now achieved by `mark_phase(... "build", "started")` at line 2124 which already runs immediately after.

### Task 1.7: Remove `phase` from scan helpers

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Lines 269-296 (`_find_next_prepare_slug`): Already covered in Task 1.2, verify no other `phase` references remain in scan functions

### Task 1.8: Update `TodoState` pydantic model

**File(s):** `teleclaude/types/todos.py`

- [x] Remove `phase` field from `TodoState` (line 39)

### Task 1.9: Update todo scaffold

**File(s):** `teleclaude/todo_scaffold.py`

- [x] Remove `phase="in_progress"` from `_BUG_STATE` (line 32). Bug scaffold should set `build="started"` instead to indicate work has begun.

### Task 1.10: Update resource validation

**File(s):** `teleclaude/resource_validation.py`

- [x] Line 1092: Replace `state.phase == "pending"` with `state.build == "pending"` (since `phase` field is removed from the model, this would fail anyway)

### Task 1.11: Update TUI types

**File(s):** `teleclaude/cli/tui/types.py`

- [x] Review `TodoStatus` enum (lines 45-62). This is a display enum unrelated to `phase` storage — may need no change if it derives from `build`/`review` already. Verify and adjust if needed.

### Task 1.12: Update roadmap.py phase derivation

**File(s):** `teleclaude/core/roadmap.py`

- [x] Lines 102-134: Replace phase-reading logic with build-based derivation. The display status (`pending`/`ready`/`in_progress`) should be derived from `build` + `dor.score`:
  - `build == pending` + `dor.score >= 8` → display "ready"
  - `build == pending` + `dor.score < 8` → display "pending"
  - `build != pending` → display "in_progress"

### Task 1.13: Replace phase check in `next_prepare()` DOR readiness

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Lines 1939-1940: Replace `get_item_phase(cwd, resolved_slug)` + `ItemPhase.PENDING.value` check with `read_phase_state(cwd, resolved_slug)` and check `build == pending`

### Task 1.14: Update `bugs list` CLI command

**File(s):** `teleclaude/cli/telec.py`

- [x] Lines 2185-2199: Replace `phase = state.get("phase", "unknown")` and the `if phase == "in_progress"` block with `build`-based status derivation:
  - `build != pending` (started or complete) → derive display status from `build`/`review` values
  - `build == pending` → status "pending"

### Task 1.15: Update diagram extractor

**File(s):** `scripts/diagrams/extract_state_machines.py`

- [x] Lines 142-183: Remove `parse_roadmap_transitions()` function entirely (it parses `set_item_phase` calls which no longer exist)
- [x] Line 251: Remove `parse_enum_members(tree, "ItemPhase")` call and related mermaid generation for the removed enum
- [x] Line 261: Remove `ItemPhase` warning check

### Task 1.16: Backward compatibility for existing state.yaml files

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] In `read_phase_state()`: remove the phase migration block (lines 347-356). After removing `phase` from `DEFAULT_STATE`, the `{**DEFAULT_STATE, **state}` merge will carry any persisted `phase` key harmlessly, and nothing reads it. Existing state.yaml files with `phase` won't break.

### Task 1.17: Update `__init__.py` exports

**File(s):** `teleclaude/core/next_machine/__init__.py`

- [x] Remove `get_item_phase`, `set_item_phase`, `ItemPhase` from exports if present

---

## Phase 2: Validation

### Task 2.1: Update tests

**Files:**

- `tests/unit/test_next_machine_state_deps.py`
- `tests/integration/test_state_machine_workflow.py`
- `tests/unit/test_next_machine_hitl.py`
- `tests/unit/test_diagram_extractors.py`
- `tests/unit/test_todo_validation.py`
- `tests/unit/core/test_roadmap_api_parity.py`
- `tests/unit/core/test_roadmap.py`
- `tests/unit/test_bug_scaffold.py`
- `tests/unit/test_mcp_server.py`
- `tests/unit/core/test_next_machine_deferral.py`
- `tests/unit/test_next_machine_group_sweep.py`

- [x] Remove all `set_item_phase` / `get_item_phase` imports and calls
- [x] Replace `"phase": "pending"` in test fixtures with just `"build": "pending"` (already there in most)
- [x] Replace `"phase": "in_progress"` with `"build": "started"`
- [x] Replace `"phase": "done"` in dependency tests with `"review": "approved"` (or remove slug from roadmap)
- [x] Update test assertions that check phase values
- [x] Run `make test`

### Task 2.2: Quality Checks

- [x] Run `make lint`
- [x] Grep entire repo for remaining `ItemPhase`, `get_item_phase`, `set_item_phase`, `"phase"` references
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
