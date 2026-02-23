# Input: tui-state-persistence

## Problem

TUI state does not survive SIGUSR2 reloads. Multiple issues:

1. **Todo metadata refresh**: `PreparationView.update_data()` only rebuilds when the slug set changes. Metadata-only changes (build_status, dor_score, review_status in state.yaml) are fetched from the daemon but stale `TodoRow` widgets remain on screen.

2. **Pane theming mode reverts**: `action_cycle_pane_theming()` sets a module-level global (`_PANE_THEMING_MODE_OVERRIDE`) that is lost on process restart. It was incorrectly routed through the daemon API (`RuntimeSettings`) instead of being TUI-local state. The daemon has no business knowing about pane theming — it's purely visual.

3. **Active tab reverts**: Always resets to "sessions" tab after reload. Never persisted.

4. **Fragile persistence architecture**: Current approach is surgical — each piece of state requires manual additions in `PersistedState` dataclass, `load_state()`, `save_state()`, and explicit `self._save_state()` calls scattered through `app.py`. Missing any of these = state lost. This is how pane theming and active tab fell through the cracks.

## Brainstormed design direction

### Persistable protocol

Generalize state persistence with a protocol that widgets implement:

```python
class Persistable:
    def get_persisted_state(self) -> dict: ...
    def load_persisted_state(self, data: dict) -> None: ...
```

`SessionsView` and `PreparationView` already implement this pattern. Extend to `StatusBar` (animation_mode, pane_theming_mode) and app-level state (active_tab).

### Auto-discovery

The app auto-discovers all `Persistable` widgets via `self.query()` — no manual listing in `_save_state()`. New widget with user state? Implement the two methods, done.

### Dirty flag + debounced auto-save

Instead of manual `self._save_state()` calls scattered through event handlers:

- Widget posts `StateChanged` message when user-mutable state changes
- App catches it, starts/resets a debounce timer (~500ms)
- Timer fires: walk all Persistable widgets, collect state, one atomic write
- No writes during rapid interactions (debounce absorbs bursts)
- Same proven pattern as `RuntimeSettings._schedule_flush()`

### State file format

Namespaced by widget, single file `~/.teleclaude/tui_state.json`:

```json
{
  "sessions": { "sticky_sessions": [...], "collapsed": [...], ... },
  "preparation": { "expanded_todos": [...] },
  "status_bar": { "animation_mode": "periodic", "pane_theming_mode": "agent" },
  "app": { "active_tab": "preparation" }
}
```

### Source of truth distinction

- **Daemon is source of truth**: session list, computers, todo metadata, TTS — comes from API. Never persist in TUI file.
- **User is source of truth**: tab selection, expanded items, pinned sessions, animation/theming choices — only exist because user did something. Must persist.

### Decouple pane theming from daemon

TUI stops reading `pane_theming_mode` from daemon settings API. Daemon API can keep it for the web frontend. TUI uses its own state file exclusively.

## Existing code references

- `teleclaude/cli/tui/state_store.py` — current surgical persistence (PersistedState dataclass)
- `teleclaude/cli/tui/app.py` — `_save_state()` with 8+ call sites, `on_mount()` restore logic
- `teleclaude/cli/tui/views/sessions.py` — `get_persisted_state()` / `load_persisted_state()` (already works)
- `teleclaude/cli/tui/views/preparation.py` — `get_persisted_state()` / `load_persisted_state()` (already works)
- `teleclaude/cli/tui/widgets/status_bar.py` — has reactives but no persistence interface
- `teleclaude/cli/tui/messages.py` — `DataRefreshed` carries `pane_theming_mode` from daemon (remove)
- `teleclaude/config/runtime_settings.py` — daemon-side pane_theming_mode (TUI stops using)
- `teleclaude/cli/tui/views/preparation.py:92-96` — slug-only comparison (the todo refresh bug)
