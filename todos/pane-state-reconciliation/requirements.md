# Requirements: pane-state-reconciliation

## Goal

Eliminate pane state corruption in the TUI tmux pane manager by replacing the fragile multi-field state model with a reconciliation-first architecture. The system should never reference a dead pane, never fail to detect externally killed panes, and survive SIGUSR2 reloads without destroying session panes.

## Scope

### In scope:

- Simplify `PaneState` to a single source of truth (`session_to_pane` dict + `active_session_id`)
- Add reconciliation: query tmux for actual panes before every `apply_layout()` and prune stale entries
- Fix SIGUSR2 reload: replace destructive `_adopt_existing_panes()` with reconciling adoption that matches surviving panes against persisted state
- Remove dead code: `seed_layout_for_reload()` in pane_bridge.py, `_is_reload` flag in app.py
- Clean up the reload lifecycle so all reload logic flows through pane_manager (not spread across 4 files)

### Out of scope:

- Changing the PaneWriter thread architecture (it works correctly)
- Changing tmux layout grid specs (LAYOUT_SPECS)
- Changing the `_build_attach_cmd` / SSH logic
- Pane theming / background color logic (separate concern)

## Success Criteria

- [ ] SIGUSR2 reload preserves all session panes (no kill + recreate cycle)
- [ ] After reload, clicking a session row uses existing pane (no flicker, no scroll history loss)
- [ ] Externally killed panes are detected on next `apply_layout()` and pruned from state
- [ ] `PaneState` has exactly 2 fields: `session_to_pane: dict[str, str]` and `active_session_id: str | None`
- [ ] All derived state (sticky_pane_ids, parent_pane_id, etc.) is computed, not stored
- [ ] `seed_layout_for_reload()` is removed from pane_bridge.py
- [ ] `_is_reload` / `TELEC_RELOAD` env var coordination is removed from app.py and telec.py
- [ ] `_adopt_existing_panes()` is replaced with `_reconcile()` that queries tmux and prunes dead entries
- [ ] Layout signature comparison still works correctly after state simplification
- [ ] All existing TUI tests pass (`make test`)
- [ ] Manual test: open TUI with 2 sticky sessions, send SIGUSR2, verify panes survive and are interactive

## Constraints

- Must not break the PaneWriter serialization guarantees (all tmux mutations via writer thread)
- Must not add new tmux subprocess calls to hot paths (per-click latency budget)
- The one `list-panes` call in `_reconcile()` is acceptable since `apply_layout` already calls multiple tmux commands
- Reconciliation must handle the case where TUI pane ID itself changed (process restart into same pane)

## Risks

- Race between PaneWriter thread and reconciliation if both reference pane IDs simultaneously (mitigated: reconciliation runs inside PaneWriter-scheduled operations)
- tmux pane IDs may be reused after kill (low risk: tmux uses monotonically increasing %N IDs within a server lifetime)
