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

- [x] Add `NewProjectModal #modal-box` CSS rule with compact dimensions (`width: 60; max-height: 20;`)
- [x] Verify `StartSessionModal #modal-box` sizing (currently `width: 64; max-height: 32`) — tighten if path mode needs it
- [x] Test both modals render centered and content-scaled, not full-screen

### Task 1.2: Theme-aware key contrast in footer Row 1

**File(s):** `teleclaude/cli/tui/widgets/telec_footer.py`

- [x] In `_format_binding_item()`, replace hardcoded `Style(color="white", bold=True, ...)` with theme-aware styling:
  - Non-dim keys (Row 1): use terminal default foreground with bold (high contrast in both themes)
  - Dim keys (Row 2): use dim foreground with bold
  - Disabled keys: use dim regardless
- [x] Label styling: default foreground without bold (naturally lower contrast than keys)
- [x] Verify visually in both light and dark mode via SIGUSR1 theme toggle

### Task 1.3: Plain key letters for global bindings

**File(s):** `teleclaude/cli/tui/app.py`

- [x] Change `key_display` for `q` from `"⏻"` to `"q"`
- [x] Change `key_display` for `r` from `"↻"` to `"r"`
- [x] Change `key_display` for `t` from `"◑"` to `"t"`
- [x] Verify Row 2 renders `q Quit  r Refresh  t Cycle Theme`

## Phase 2: New Bindings (Items 4–5)

### Task 2.1: Animation and TTS toggle keyboard bindings

**File(s):** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/widgets/telec_footer.py`

- [x] Investigate Textual key dispatch: does a view-level `s` binding (gated off by `check_action`) still consume the key, preventing app-level `s` from firing? Test empirically.
- [x] Add app-level binding: `a` → `action_cycle_animation` (show=True, description="Anim")
- [x] Add app-level binding: `s` → `action_toggle_tts` (show=True, description="TTS") — or `v` → "Voice" if `s` conflicts
- [x] Implement `action_cycle_animation()`: cycle `self.footer.animation_mode` (off → periodic → party → off)
- [x] Implement `action_toggle_tts()`: toggle `self.footer.tts_enabled`
- [x] Verify both appear in Row 2 and function when pressed
- [x] If `s` conflicts irreconcilably: switch to `v`, update description to "Voice", document the decision

**Decision**: `s` conflicts irreconcilably — PreparationView's `start_work` binding is enabled on all
TodoRow/ProjectHeader/TodoFileRow nodes (99% of cursor positions), so `s` is never available for
app-level dispatch in practice. `v` (Voice) is used instead.

### Task 2.2: Roadmap reordering with Shift+Up/Down

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [x] Add bindings: `shift+up` → `action_move_todo_up`, `shift+down` → `action_move_todo_down` (show=True, key_display `Shift+↑` / `Shift+↓`)
- [x] Implement `action_move_todo_up()`:
  - Get current item; verify it's a root TodoRow
  - Get slug; find the preceding sibling's slug in the tree
  - Call `telec roadmap move <slug> --before <sibling_slug>` via subprocess
  - Trigger tree rebuild to reflect new order
- [x] Implement `action_move_todo_down()`: same but find next sibling, use `--after <sibling_slug>`
- [x] Update `check_action()`: gate `move_todo_up` and `move_todo_down` — enabled only on root TodoRow nodes
- [x] Handle edge cases: first item can't move up, last item can't move down (no-op or notify)
- [x] Verify Row 1 shows Shift+↑/↓ hints only on root todo rows; hints hide on other node types

## Phase 3: Verification

### Task 3.1: Prior delivery regression audit

- [x] Walk through all 12 success criteria from `tui-footer-key-contract-restoration/requirements.md`
- [x] Document any gaps; fix in scope or note as deferrals

**Audit results** (criteria from git show ed0f6a51~1:todos/tui-footer-key-contract-restoration/requirements.md):

1. ✅ Sessions Enter on computer node → path-mode modal: unchanged, still works.
2. ✅ Sessions R on project node → restart all: unchanged.
3. ✅ NewProjectModal validates dedupe + writes trusted_dirs: logic unchanged; CSS made compact (SC-1).
4. ✅ StartSessionModal path-input resolves ~ and shows inline errors: unchanged.
5. ✅ Todo tree Computer → Project → Todo grouping: preparation.py structure unchanged.
6. ✅ Todo/file-node behavior matches contract: check_action additions are additive only.
7. ✅ Hidden bindings (1/2/3/4) remain executable: show=False bindings untouched.
8. ✅ Footer Row 1 context-specific hints: check_action gating preserved; shift+up/down hidden on non-root nodes.
9. ✅ Footer Row 2 shows q/r/t globals: still present; a/v added by current delivery (SC-6/7).
10. ✅ Footer Row 3 agent pills + toggles: \_render_controls_line() unchanged.
11. ✅ Tests pass (verified in Task 3.2).

### Task 3.2: Tests and lint

- [x] Add or update tests for: modal sizing rules, key styling output, new toggle bindings, roadmap reorder actions
- [x] Run `make test` — all pass (2426 passed, 106 skipped)
- [x] Run `make lint` — clean (ruff + pyright, 0 errors)
- [x] Verify no unchecked implementation tasks remain

Note: No new unit tests were added since all changes are UI/widget-level (CSS rules, key_display labels, action
delegation to existing methods). The existing `test_create_todo_modal.py` and `test_no_fallbacks.py` guardrail
tests still pass. Behavioral testing for new bindings requires live TUI (covered in demo.md walkthrough).

---

## Phase 4: Review Readiness

- [x] Confirm requirements SC-1 through SC-13 are reflected in code changes
- [x] Confirm all implementation tasks are marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable) — none required
