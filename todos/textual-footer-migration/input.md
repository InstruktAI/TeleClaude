# Input: textual-footer-migration

<!-- Brain dump — raw thoughts, ideas, context. Prepare when ready. -->

## Problem

The current `ActionBar` widget uses hardcoded strings per view to display key hints. This requires manual sync between each view's `BINDINGS` list and the `ActionBar._CONTEXT_BAR` / `_SESSION_CONTEXT` dicts. We just shipped `todo-remove-cli-option` with the `R` keybinding registered in `BINDINGS` but invisible in the TUI because the ActionBar string wasn't updated. The builder, reviewer, and demo all missed it.

This class of bug is eliminated by using Textual's built-in `Footer` widget, which auto-discovers bindings from the focused widget and its ancestors.

## User Requirements

- **Dynamic binding display**: When a binding is added to any view's `BINDINGS`, it must appear in the footer automatically. No hardcoded string maintenance.
- **Compact / C64-style**: Reduce screen real estate. Current footer area is 4 lines (3 ActionBar + 1 StatusBar). Target: 2 lines (1 Footer + 1 StatusBar). Use Unicode symbols for keys and binding groups to compress related keys.
- **Beautiful styling**: Style key portion differently from description. Keys bold/accent, descriptions dimmed. Should integrate with the existing TeleClaude theming system.
- **Keep everything visible**: Don't hide bindings. Users should be able to learn all available keys from the footer. Make it fit by being denser, not by hiding.
- **Sessions view cursor-context**: The sessions view currently changes hints based on cursor position (session row vs computer row vs project row). This must be preserved.

## Research Findings (Textual Footer)

### Automatic Binding Discovery

- Footer reads `self.screen.active_bindings` — merges bindings from focused widget + all ancestors
- Subscribes to `self.screen.bindings_updated_signal` for live updates
- Context-sensitive by default: focus changes trigger footer recompose

### Binding Groups (`Binding.Group`)

Groups let related keys share a single description label:

```python
nav_group = Binding.Group(description="Nav", compact=True)
BINDINGS = [
    Binding("up", "cursor_up", "", group=nav_group, key_display="\u2191"),
    Binding("down", "cursor_down", "", group=nav_group, key_display="\u2193"),
]
# Renders as grouped: up-arrow down-arrow Nav
```

### CSS Component Classes (on FooterKey)

```css
FooterKey .footer-key--key {
  /* style the key label */
}
FooterKey .footer-key--description {
  /* style the description */
}
```

Additional selectors: `FooterKey.-compact`, `FooterKey.-grouped`, `FooterKey.-disabled`, `FooterKey.-command-palette`, `FooterLabel`, `KeyGroup`, `KeyGroup.-compact`.

### Design Token CSS Variables

`$footer-foreground`, `$footer-background`, `$footer-key-foreground`, `$footer-key-background`, `$footer-description-foreground`, `$footer-description-background`, `$footer-item-background`

### key_display

- Plain string only (no Rich markup), but Unicode symbols work perfectly
- Override globally via `App.get_key_display(binding)`
- Examples: arrows for navigation, return symbol for enter, space symbol for space, +/- for expand/collapse

### Compact Mode

`Footer(compact=True)` removes padding around keys. Saves ~2 cells per binding.

### Subclassing

Can subclass `Footer` and override `compose()` while keeping auto-discovery. `FooterKey`, `FooterLabel`, `KeyGroup` are importable from `textual.widgets._footer` (private API — pin Textual version).

### Important Implementation Notes

- Footer is a `ScrollableContainer` with `layout: horizontal` and `scrollbar-size: 0 0`. Overflowing bindings scroll horizontally.
- `_bindings_ready` guard in `compose()` prevents rendering before bindings are available.
- `data_bind(compact=Footer.compact)` is needed when yielding FooterKey from custom compose.
- Current Textual version in project: 8.0.0

## Current Architecture

### Files involved

- `teleclaude/cli/tui/widgets/action_bar.py` — custom ActionBar (DELETE)
- `teleclaude/cli/tui/widgets/footer.py` — legacy curses Footer class (already unused by Textual app)
- `teleclaude/cli/tui/app.py` — composes ActionBar + StatusBar in footer area
- `teleclaude/cli/tui/telec.tcss` — CSS for #footer, ActionBar, StatusBar
- `teleclaude/cli/tui/messages.py` — `CursorContextChanged` message
- `teleclaude/cli/tui/views/preparation.py` — BINDINGS uses tuples
- `teleclaude/cli/tui/views/sessions.py` — BINDINGS uses tuples, posts CursorContextChanged
- `teleclaude/cli/tui/views/jobs.py` — BINDINGS uses tuples
- `teleclaude/cli/tui/views/config.py` — BINDINGS uses tuples

### Current BINDINGS format (all views use tuples)

```python
BINDINGS = [
    ("up", "cursor_up", "Previous"),
    ("R", "remove_todo", "Remove"),
]
```

Must be migrated to `Binding` objects for `key_display`, `group`, and `show` support.

### Sessions cursor-context challenge

`SessionsView` posts `CursorContextChanged(item_type="session"|"computer"|"project")` and ActionBar switches between `_SESSION_CONTEXT` dicts. With Textual Footer, this needs to be solved differently — likely by toggling `Binding.show` dynamically based on cursor position, or by accepting a simplified approach where all session bindings are always visible.

## Design Direction

- Replace ActionBar with `Footer(compact=True, show_command_palette=False)`
- Convert all view BINDINGS from tuples to `Binding` objects
- Use `Binding.Group(compact=True)` for navigation keys (up/down/left/right) and expand/collapse (+/-)
- Use `key_display` with Unicode symbols for common keys
- Style via CSS component classes + design token variables integrated with TeleClaude theming
- StatusBar stays as-is (1 line, below Footer)
- Net result: 4 lines to 2 lines footer area
