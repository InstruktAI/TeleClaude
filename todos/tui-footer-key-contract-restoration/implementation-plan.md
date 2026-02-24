# Implementation Plan: tui-footer-key-contract-restoration

## Overview

Implement a strict footer/key interaction contract by keeping a unified 3-row footer and enforcing context/global visibility through binding metadata and `check_action` filtering. Restore computer grouping in todo view and unify modal validation behavior for path-aware session/project creation.

## Phase 1: Lock binding visibility and action semantics

### Task 1.1: Sessions view keymap contract

**Files:** `teleclaude/cli/tui/views/sessions.py`

- [ ] Define exact node-aware visibility for computer/project/session actions via `check_action`.
- [ ] Ensure `Enter` routes correctly by node:
  - Computer -> New Session modal (path input mode)
  - Project -> New Session modal (project mode)
  - Session -> Focus
- [ ] Ensure `R` semantics are node-sensitive:
  - Computer -> restart all for computer
  - Project -> restart all for project
  - Session -> restart session
- [ ] Ensure `+/-` semantics are node-sensitive for computer/project trees.
- [ ] Ensure no stale/extra hints leak into footer from legacy bindings.

### Task 1.2: Preparation/Todo view keymap contract

**Files:** `teleclaude/cli/tui/views/preparation.py`

- [ ] Restore computer nodes in tree navigation model.
- [ ] Enforce node-aware key visibility for computer/project/todo/file rows.
- [ ] Map project `Enter` to New Todo default action.
- [ ] Keep todo `Enter` active for collapse/expand but hidden from footer.
- [ ] Keep file-row actions visible (`Space Preview`, `Enter Edit`).
- [ ] Ensure `p/s` launch StartSession modal with required command prefill.

### Task 1.3: Global bindings visibility policy

**Files:** `teleclaude/cli/tui/app.py`

- [ ] Keep tab-switch keys (`1/2/3/4`) bound and functional.
- [ ] Mark tab-switch bindings hidden from footer.
- [ ] Ensure global row visible list is exactly: `q`, `r`, `t`, `s`, `a`.

## Phase 2: Unified footer rendering contract

### Task 2.1: Row partitioning in unified footer

**Files:** `teleclaude/cli/tui/widgets/telec_footer.py`

- [ ] Keep single widget with exactly 3 rendered lines.
- [ ] Row 1 consumes non-app (context) bindings.
- [ ] Row 2 consumes app-level (global) bindings.
- [ ] Row 3 renders agent pills + controls.
- [ ] Preserve click handling for row-3 toggles.

### Task 2.2: Layout hardening

**Files:** `teleclaude/cli/tui/telec.tcss`, `teleclaude/cli/tui/app.py`

- [ ] Footer container and widget heights fixed to prevent clipping.
- [ ] Add/keep top separator as needed for readability.
- [ ] Verify row rendering in narrow widths and normal desktop width.

## Phase 3: Modal/path validation enhancements

### Task 3.1: New Session modal path-input mode (computer node)

**Files:** `teleclaude/cli/tui/widgets/modals.py`, `teleclaude/cli/tui/views/sessions.py` (and related modal wiring)

- [ ] Reuse existing StartSession modal flow and add inline path input mode.
- [ ] Resolve tilde paths before validation.
- [ ] Validate path existence on submit.
- [ ] Keep modal open on validation failure and show inline field error state.

### Task 3.2: New Project modal behavior and trusted_dirs integration

**Files:** `teleclaude/cli/tui/widgets/modals.py`, `teleclaude/cli/tui/views/sessions.py`, relevant API/config layer

- [ ] Modal fields: name, description, path.
- [ ] Reuse same path validation component/logic.
- [ ] Block duplicates for existing project/path.
- [ ] On success, persist into `trusted_dirs` and refresh visible tree.

## Phase 4: Test coverage and verification

### Task 4.1: Footer and keymap tests

**Files:** `tests/unit/test_tui_footer_migration.py` (or split into focused suite)

- [ ] Assert 3-row footer rendering contract.
- [ ] Assert node-aware visibility for Sessions tree.
- [ ] Assert node-aware visibility for Todo tree.
- [ ] Assert hidden-but-active behavior (`1/2/3/4`, todo-row Enter).

### Task 4.2: Modal validation tests

**Files:** modal/view unit tests

- [ ] Assert tilde resolution and path validation errors keep modal open.
- [ ] Assert duplicate project/path is blocked.
- [ ] Assert trusted_dirs update on successful new project.

### Task 4.3: Interactive verification

- [ ] Run TUI and verify each node context displays expected row-1 hints.
- [ ] Verify row-2 global hints fixed list.
- [ ] Verify row-3 controls visible and interactive.
- [ ] Verify computer nodes appear in todo view and behaviors match contract.

## Rollout Notes

- Implement in small commits by phase to isolate regressions.
- Favor adapter- and modal-level reuse over introducing parallel components.
- Keep footer hint source authoritative from active bindings to avoid drift.
