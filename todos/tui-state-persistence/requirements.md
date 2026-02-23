# Requirements: tui-state-persistence

## Goal

Make TUI state fully survive SIGUSR2 reloads and process restarts by introducing a generalized `Persistable` protocol with debounced auto-save, replacing the current surgical per-field persistence approach.

Additionally fix the todo metadata refresh bug so that `PreparationView` rebuilds on metadata changes, not just slug set changes.

## Scope

### In scope

- `Persistable` protocol: `get_persisted_state() -> dict` / `load_persisted_state(data: dict)`
- Auto-discovery of Persistable widgets via Textual query at save time
- Debounced auto-save: `StateChanged` message triggers a ~500ms debounced write, replacing all manual `_save_state()` calls
- Namespaced state file format in `~/.teleclaude/tui_state.json`
- Migrate existing widgets to Persistable:
  - `SessionsView` (already has the methods — adapt to dict-based interface)
  - `PreparationView` (already has the methods — adapt to dict-based interface)
  - `StatusBar` (new: animation_mode, pane_theming_mode)
  - App-level state (new: active_tab)
- Decouple pane theming mode from daemon API on TUI side (stop reading from/writing to daemon settings; use tui_state.json)
- Fix `PreparationView.update_data()` to detect metadata changes (not just slug changes)
- Backward compatibility: migrate old flat-format tui_state.json on load

### Out of scope

- Daemon-side cleanup of pane_theming_mode from RuntimeSettings/API (web frontend still uses it)
- Persisting scroll positions or cursor positions
- Persisting data that comes from the daemon API (session lists, computer info, todo content)
- Changes to the web frontend

## Success Criteria

- [ ] Editing `todos/*/state.yaml` (metadata change) updates the TUI todo view within ~2s without manual refresh
- [ ] Cycling pane theming mode survives SIGUSR2 reload
- [ ] Active tab survives SIGUSR2 reload
- [ ] Animation mode continues to survive SIGUSR2 reload (no regression)
- [ ] Sticky sessions, collapsed sessions, expanded todos, highlights continue to survive SIGUSR2 reload (no regression)
- [ ] `~/.teleclaude/tui_state.json` uses namespaced format after first save
- [ ] Old flat-format tui_state.json is migrated transparently on load
- [ ] No manual `_save_state()` calls remain in app.py — all persistence is driven by `StateChanged` message + debounce
- [ ] Adding persistence to a new widget requires only: implement `Persistable`, post `StateChanged` on mutation
- [ ] TTS toggle still works via daemon API (unaffected)
- [ ] Existing tests pass (`test_tui_footer_widget.py`, `test_runtime_settings.py`)

## Constraints

- Must not break existing persistence for sessions state (sticky, highlights, etc.)
- Debounce timer must be short enough that SIGUSR2 during rapid interaction doesn't lose state (the SIGUSR2 handler should flush immediately before exit, bypassing debounce)
- CLI `--view` flag must override persisted active tab
- Widget IDs used as namespace keys must be stable across versions

## Risks

- Backward compat migration from flat to namespaced format could lose state if migration logic has bugs — mitigate with defensive parsing and logging
- Debounce timer vs SIGUSR2 race — mitigate by having SIGUSR2 handler do an immediate synchronous save before exit (already the pattern in `_sigusr2_reload`)
