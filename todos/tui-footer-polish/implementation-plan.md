# Implementation Plan: tui-footer-polish

## Overview

Six independent fixes targeting the TUI footer, modals, and preparation view. Most changes are styling/binding updates (low risk). Roadmap reordering (item 5) is the most complex — it adds new actions with CLI integration. All changes are localized to the TUI layer with no core logic impact.

## Key Files

| File                                         | Purpose                                          |
| -------------------------------------------- | ------------------------------------------------ |
| `teleclaude/cli/tui/telec.tcss`              | Modal CSS sizing rules                           |
| `teleclaude/cli/tui/widgets/telec_footer.py` | `_format_binding_item()` styling, Row 3 controls |
| `teleclaude/cli/tui/app.py`                  | Global BINDINGS, action handlers for toggles     |
| `teleclaude/cli/tui/views/preparation.py`    | Shift+Up/Down bindings, check_action gating      |

## Phase 1: Visual Fixes (Items 1–3)

### Task 1.1: Compact modal sizing

**File(s):** `teleclaude/cli/tui/telec.tcss`

- [ ] Add `NewProjectModal #modal-box` CSS rule with compact dimensions (`width: 60; max-height: 20;`)
- [ ] Verify `StartSessionModal #modal-box` sizing (currently `width: 64; max-height: 32`) — tighten if path mode needs it
- [ ] Test both modals render centered and content-scaled, not full-screen

### Task 1.2: Theme-aware key contrast in footer Row 1

**File(s):** `teleclaude/cli/tui/widgets/telec_footer.py`

- [ ] In `_format_binding_item()`, replace hardcoded `Style(color="white", bold=True, ...)` with theme-aware styling:
  - Non-dim keys (Row 1): use terminal default foreground with bold (high contrast in both themes)
  - Dim keys (Row 2): use dim foreground with bold
  - Disabled keys: use dim regardless
- [ ] Label styling: default foreground without bold (naturally lower contrast than keys)
- [ ] Verify visually in both light and dark mode via SIGUSR1 theme toggle

### Task 1.3: Plain key letters for global bindings

**File(s):** `teleclaude/cli/tui/app.py`

- [ ] Change `key_display` for `q` from `"⏻"` to `"q"`
- [ ] Change `key_display` for `r` from `"↻"` to `"r"`
- [ ] Change `key_display` for `t` from `"◑"` to `"t"`
- [ ] Verify Row 2 renders `q Quit  r Refresh  t Cycle Theme`

## Phase 2: New Bindings (Items 4–5)

### Task 2.1: Animation and TTS toggle keyboard bindings

**File(s):** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/widgets/telec_footer.py`

- [ ] Investigate Textual key dispatch: does a view-level `s` binding (gated off by `check_action`) still consume the key, preventing app-level `s` from firing? Test empirically.
- [ ] Add app-level binding: `a` → `action_cycle_animation` (show=True, description="Anim")
- [ ] Add app-level binding: `s` → `action_toggle_tts` (show=True, description="TTS") — or `v` → "Voice" if `s` conflicts
- [ ] Implement `action_cycle_animation()`: cycle `self.footer.animation_mode` (off → periodic → party → off)
- [ ] Implement `action_toggle_tts()`: toggle `self.footer.tts_enabled`
- [ ] Verify both appear in Row 2 and function when pressed
- [ ] If `s` conflicts irreconcilably: switch to `v`, update description to "Voice", document the decision

### Task 2.2: Roadmap reordering with Shift+Up/Down

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [ ] Add bindings: `shift+up` → `action_move_todo_up`, `shift+down` → `action_move_todo_down` (show=True, key_display `Shift+↑` / `Shift+↓`)
- [ ] Implement `action_move_todo_up()`:
  - Get current item; verify it's a root TodoRow
  - Get slug; find the preceding sibling's slug in the tree
  - Call `telec roadmap move <slug> --before <sibling_slug>` via subprocess
  - Trigger tree rebuild to reflect new order
- [ ] Implement `action_move_todo_down()`: same but find next sibling, use `--after <sibling_slug>`
- [ ] Update `check_action()`: gate `move_todo_up` and `move_todo_down` — enabled only on root TodoRow nodes
- [ ] Handle edge cases: first item can't move up, last item can't move down (no-op or notify)
- [ ] Verify Row 1 shows Shift+↑/↓ hints only on root todo rows; hints hide on other node types

## Phase 3: Verification

### Task 3.1: Prior delivery regression audit

- [ ] Walk through all 12 success criteria from `tui-footer-key-contract-restoration/requirements.md`
- [ ] Document any gaps; fix in scope or note as deferrals

### Task 3.2: Tests and lint

- [ ] Add or update tests for: modal sizing rules, key styling output, new toggle bindings, roadmap reorder actions
- [ ] Run `make test` — all pass
- [ ] Run `make lint` — clean
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [ ] Confirm requirements SC-1 through SC-13 are reflected in code changes
- [ ] Confirm all implementation tasks are marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
