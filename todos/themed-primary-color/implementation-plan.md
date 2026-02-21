# Implementation Plan: themed-primary-color

## Overview

Textual generates CSS variables like `$border`, `$block-cursor-background`, and `$scrollbar-*` from the `Theme.primary` field. Today all theme variants use `primary="#808080"` (gray). We add agent-variant themes with `primary="#d7af87"` (Claude orange) and switch between peaceful/agent themes when the carousel level changes. The standalone editor gets theme registration via a `--theme` CLI flag.

## Phase 1: Core Changes

### Task 1.1: Create agent-variant theme objects

**File(s):** `teleclaude/cli/tui/app.py`

- [x] Create `_TELECLAUDE_DARK_AGENT_THEME` — clone of `_TELECLAUDE_DARK_THEME` with:
  - `name="teleclaude-dark-agent"`
  - `primary="#d7af87"` (Claude normal dark)
  - `secondary="#af875f"` (Claude muted dark)
  - All other fields identical (same `variables` dict, same structural colors)
- [x] Create `_TELECLAUDE_LIGHT_AGENT_THEME` — clone of `_TELECLAUDE_LIGHT_THEME` with:
  - `name="teleclaude-light-agent"`
  - `primary="#875f00"` (Claude normal light)
  - `secondary="#af875f"` (Claude muted light)
- [x] Register both new themes in `TelecApp.__init__()` alongside the existing two

### Task 1.2: Switch theme on carousel cycle

**File(s):** `teleclaude/cli/tui/app.py`

- [x] In `action_cycle_pane_theming()`, after setting the new mode, determine if the new level is peaceful (0) or agent (1-4)
- [x] Set `self.theme` to the appropriate variant (`teleclaude-dark` vs `teleclaude-dark-agent`, respecting dark/light mode)
- [x] Also set the correct theme on app startup based on the initial pane theming level

### Task 1.3: Register themes in EditorApp

**File(s):** `teleclaude/cli/editor.py`

- [x] Import the four theme objects from `teleclaude.cli.tui.app`
- [x] Add `--theme` CLI argument (default: `teleclaude-dark`)
- [x] In `EditorApp.__init__()`, register all four themes and set `self.theme` to the requested one
- [x] Update the editor's inline CSS to remove hardcoded `$surface` / `$text` references that may conflict (or verify they work with the registered theme)

### Task 1.4: Pass theme name from TUI to editor

**File(s):** `teleclaude/cli/tui/views/preparation.py`, `teleclaude/cli/tui/pane_manager.py` (or wherever the editor command is built)

- [x] Find where the editor subprocess command is constructed (e.g., `_editor_command()`)
- [x] Append `--theme <active-theme-name>` to the command based on current pane theming level and dark/light mode

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Add or update tests for theme registration (verify all four themes register without error)
- [x] Run `make test`

### Task 2.2: Visual Verification

- [x] Launch TUI, cycle through all 5 carousel levels — confirm focus borders change from gray to warm orange at level 1
- [x] At each level, focus a TextArea, Input, Select, Button — confirm border color matches expectation
- [x] Press spacebar to preview a file — confirm editor has warm/gray borders matching the TUI
- [x] Switch to light mode and repeat
- [x] Confirm scrollbar accents follow the theme

### Task 2.3: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
