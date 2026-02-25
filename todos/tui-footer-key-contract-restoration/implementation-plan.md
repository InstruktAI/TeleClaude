# Implementation Plan: tui-footer-key-contract-restoration

## Overview

This plan only covers remaining gaps. The unified 3-row footer baseline already exists and is not reimplemented here. Work focuses on node-specific key behavior, todo computer grouping restoration, and modal/path validation contracts.

## Phase 1: Sessions key/action contract completion

### Task 1.1: Node-aware Sessions actions

**Files:** `teleclaude/cli/tui/views/sessions.py`

- [ ] Enforce exact computer/project/session action visibility through `check_action`.
- [ ] Ensure `Enter` routes by node:
  - Computer -> New Session modal with path input mode
  - Project -> New Session modal in project mode
  - Session -> Focus
- [ ] Ensure `R` semantics are node-sensitive:
  - Computer -> restart all for computer
  - Project -> restart all for project
  - Session -> restart selected session
- [ ] Ensure `+/-` is scoped correctly for computer/project collapse behavior.

### Task 1.2: Global visibility guardrail

**Files:** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/widgets/telec_footer.py`

- [ ] Keep global visible actions exactly `q`, `r`, `t`, `s`, `a`.
- [ ] Keep `1/2/3/4` active but hidden.
- [ ] Ensure no hidden navigation/view-switch keys leak back into footer rows.

## Phase 2: Todo tree and key contract completion

### Task 2.1: Restore computer grouping in Todo tree

**Files:** `teleclaude/cli/tui/views/preparation.py` and related tree/model helpers

- [ ] Restore computer -> project -> todo/files grouping.
- [ ] Preserve expected sort/group ordering.

### Task 2.2: Node-aware Todo actions

**Files:** `teleclaude/cli/tui/views/preparation.py`

- [ ] Computer node: `n`, `+/-`.
- [ ] Project node: `t`, `Enter` (default new todo), `b`, `+/-`.
- [ ] Todo node: `t`, `p`, `s`, `R`, hidden-active `Enter` for collapse/expand.
- [ ] File node: `Space Preview`, `Enter Edit`.
- [ ] Ensure `p/s` prefill `/next-prepare <slug>` and `/next-work <slug>` in StartSession modal.

## Phase 3: Modal/path validation contract completion

### Task 3.1: Computer-level New Session path mode

**Files:** `teleclaude/cli/tui/widgets/modals.py`, `teleclaude/cli/tui/views/sessions.py`

- [ ] Extend existing modal flow with path input for computer-node session launch.
- [ ] Resolve `~` before validating path.
- [ ] Keep modal open on invalid path and show inline error state.

### Task 3.2: New Project validation and trusted_dirs update

**Files:** `teleclaude/cli/tui/widgets/modals.py`, `teleclaude/cli/tui/views/sessions.py`, relevant config/update layer

- [ ] Require name, description, and path.
- [ ] Reuse shared path validation logic.
- [ ] Block duplicate project/path creation.
- [ ] On success, persist to `trusted_dirs` and refresh tree.

## Phase 4: Tests and verification for remaining gaps

### Task 4.1: Key visibility and behavior tests

**Files:** `tests/unit/test_tui_footer_migration.py` and/or targeted Sessions/Preparation view tests

- [ ] Assert Sessions node-specific key visibility and behavior.
- [ ] Assert Todo node-specific key visibility and behavior.
- [ ] Assert hidden-but-active behavior (`1/2/3/4`, todo-row `Enter`).
- [ ] Assert global visible list remains exactly `q`, `r`, `t`, `s`, `a`.

### Task 4.2: Modal validation tests

**Files:** modal/view unit tests

- [ ] Assert `~` resolution and path validation failure UX for New Session modal.
- [ ] Assert duplicate project/path is blocked.
- [ ] Assert successful new project writes to `trusted_dirs`.

## Rollout Notes

- Ship as small focused commits by phase.
- Reuse existing footer/modal infrastructure; avoid another footer architecture change.
- Treat the current 3-row footer as fixed baseline and regressions as bugs.
