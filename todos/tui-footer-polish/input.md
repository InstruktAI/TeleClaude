# Input: tui-footer-polish

Post-delivery polish for the TUI footer after tui-footer-key-contract-restoration.
User observed multiple visual and functional gaps during demo walkthrough.

## 1. NewProjectModal sizing

The NewProjectModal takes over the entire screen. It only has 4 input fields (name, description, path, error label). It should scale to its contents — compact modal, not full-screen overlay. Same sizing fix likely needed for StartSessionModal in path_mode.

## 2. Footer Row 1 — key coloring / contrast

In light mode, the key indicators (e.g., `n`, `b`, `p`, `R`) render in white on a white-ish background — zero contrast. The user expects:

- **Keys** (the letter/shortcut): dark/black — these are actionable, must stand out.
- **Labels** (the description text): the default contrastful gray that's below black in the light theme palette.
- Follow the same paradigm for dark mode (keys bright/white, labels dimmed gray).
- This is a theming/styling fix in `TelecFooter._format_binding_item()` and/or the CSS.

## 3. Global Row 2 — replace unicode icons with plain key letters

Current state: `q` renders as `⏻`, `r` as `↻`, `t` as `◑`. Users can't tell what key to press.

Fix: change `key_display` in app.py BINDINGS to show the actual key letter:

- `q` Quit (not `⏻`)
- `r` Refresh (not `↻`)
- `t` Cycle Theme (not `◑`)

The global row is already dimmed. The keys should be the plain lowercase letter.

## 4. Missing global keyboard bindings for toggles

Row 3 has clickable toggle icons for TTS and Animation, but there are no keyboard bindings for them. They need to be promoted to global bindings shown in Row 2:

- `a` → Animation toggle (cycle off/periodic/party)
- `s` → Speech/TTS toggle

These should be app-level `BINDINGS` with `show=True` so they appear in the global hints row. The Row 3 click targets remain as-is for mouse users.

Note: `s` conflicts with `start_work` in the preparation view. Both are context-sensitive — `s` in prep view is only active on todo nodes. The global `s` for TTS should work when no view-level `s` binding is active, or use a different key if conflict is unavoidable.

## 5. Shift+Up/Down — roadmap reordering in Preparation view

New feature: on root todo rows in the Preparation view, `Shift+Up` and `Shift+Down` move the todo up/down in the roadmap ordering.

- Only applies to root-level todos (not sub-todos, not file rows, not headers).
- Calls `telec roadmap move <slug> --before <other-slug>` or similar.
- Rebuilds the tree after move to reflect new order.
- Footer should show `Shift+↑` / `Shift+↓` hints when on a root todo row.
- Guard with `check_action()` — disabled on non-root-todo nodes.

## 6. Requirements alignment audit

Verify all items from the tui-footer-key-contract-restoration requirements were actually delivered and are working. The user observed gaps — confirm each success criterion from the original requirements.md against the running TUI. Document any gaps found as part of this todo's requirements.

## Context

- Prior delivery: `tui-footer-key-contract-restoration` (merged to main)
- All projects are on one computer ("MozBook") so ComputerHeader is a single row
- Footer is `TelecFooter` — custom 3-row widget (Row 1: context, Row 2: global, Row 3: agent pills + toggles)
- `check_action()` gating works correctly (verified via simulation)
- Key coloring is in `TelecFooter._format_binding_item()` using Rich `Style` objects
- Global bindings in `teleclaude/cli/tui/app.py` BINDINGS list
- Modal sizing in `teleclaude/cli/tui/widgets/modals.py` CSS
