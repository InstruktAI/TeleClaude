# Requirements: textual-footer-migration

## Goal

Replace the custom `ActionBar` widget with Textual's built-in `Footer` widget to eliminate the class of bugs where key bindings are registered in views but not displayed in the UI. The Footer auto-discovers bindings from the focused widget and its ancestors, making hint display maintenance-free.

## In Scope

- Delete `ActionBar` widget and replace with `Footer(compact=True, show_command_palette=False)` in `app.py` compose.
- Convert all view `BINDINGS` from tuple format to `Binding` objects with `key_display` (Unicode symbols for common keys).
- Use `Binding.Group(compact=True)` for navigation keys (up/down/left/right) and expand/collapse (+/-).
- Style the Footer via TCSS using Textual's CSS component classes (`FooterKey .footer-key--key`, `.footer-key--description`) and design token variables (`$footer-*`), integrated with TeleClaude's existing theme system.
- Reduce footer area from 4 lines (3 ActionBar + 1 StatusBar) to 2 lines (1 Footer + 1 StatusBar).
- Remove `CursorContextChanged` message and its handler chain in `app.py`. Textual's Footer auto-switches bindings when focus moves between views.
- **Dynamic Footer Context**: For hierarchical tree views (`SessionsView` and `PreparationView`), the Footer must update its shown bindings when the internal `cursor_index` changes, even if focus remains on the view.
- **PreparationView Context**:
  - Project Node: Default action is "New todo" (n). Hide "Remove" (R) and "Enter" hint.
  - To-do Node: Show "Prepare" (p), "Start work" (s), "Remove" (R).
  - File Node: Show "Preview" (space) and "Edit" (Enter). Inherit to-do parent context (e.g., "Remove" (R) should still work to delete the parent to-do).
- **SessionsView Context**:
  - Computer Node: Add/restore "Restart All" (Shift+R or Shift+A - research which one) binding. Hide "New session" (n).
  - Project Node: Default action is "New session" (n).
  - Session Node: Show "Kill session" (k) and "Restart session" (R).
- **UI Styling**:
  - Indicate the default action (the one triggered by "Enter") by making its binding (both key and label) **bold** in the footer.
  - Eliminate redundant "Enter" hint if the default key is visually indicated.
- **Workflow Improvements**:
  - "Prepare" (p) and "Start work" (s) must always open `StartSessionModal` pre-filled with `/next-prepare` or `/next-work` (omitting slug on project node) instead of silent background dispatch.
- Remove `teleclaude/cli/tui/widgets/action_bar.py`.
- Remove `teleclaude/cli/tui/widgets/footer.py` (legacy curses stub, already unused).
- Convert `TelecApp.BINDINGS` from tuples to `Binding` objects with appropriate `key_display`.

## Out of Scope

- Subclassing `Footer` or using private Textual API (`textual.widgets._footer`).
- Changing `StatusBar` widget behavior or layout.
- Modifying any view logic beyond `BINDINGS` format conversion.
- Adding new key bindings or changing existing binding behavior.
- Pane manager, theme system, or animation changes.

## Success Criteria

- [ ] New key bindings added to any view's `BINDINGS` list automatically appear in the footer without any other file changes.
- [ ] Footer occupies 1 line (compact mode), total footer area is 2 lines (Footer + StatusBar).
- [ ] Navigation keys (arrows, +/-) render as grouped with Unicode symbols.
- [ ] Footer keys visually integrate with TeleClaude dark/light/agent themes.
- [ ] No `ActionBar` references remain in the codebase.
- [ ] No `CursorContextChanged` message or handler remains.
- [ ] All existing key bindings continue to function identically.
- [ ] `make test` passes.
- [ ] `make lint` passes.

## Constraints

- Textual version is 8.0.0 — use only public API surface.
- Footer must show all bindings (no hidden bindings) — density via compact mode and groups, not hiding.
- Must integrate with existing theme registration (dark/light/agent variants).

## Risks

- Binding groups or `key_display` may render unexpectedly in compact mode — verify visually after implementation.
- If any view bindings have `show=False` (hidden), Footer won't display them — audit all bindings during conversion.
- Footer horizontal scroll for overflow may look odd in narrow terminals — acceptable tradeoff per input.md design direction.
