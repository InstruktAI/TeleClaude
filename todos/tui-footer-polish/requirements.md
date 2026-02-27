# Requirements: tui-footer-polish

## Goal

Polish the TUI footer and related UI after the `tui-footer-key-contract-restoration` delivery. Address visual and functional gaps observed during demo walkthrough: modal sizing, key contrast, icon readability, missing keyboard bindings, and roadmap reordering.

## Scope

### In scope

1. **Modal sizing** — Compact `NewProjectModal` (and `StartSessionModal` path mode if needed) to fit content, not fill screen.
2. **Key contrast (Row 1)** — Theme-aware key styling in `_format_binding_item()` so keys are readable in both light and dark mode.
3. **Plain key letters (Row 2)** — Replace unicode icons (`⏻`, `↻`, `◑`) with actual key letters (`q`, `r`, `t`) in global bindings.
4. **Toggle keyboard bindings** — Add `a` (animation cycle) and `s` or fallback key (TTS toggle) as global app bindings visible in Row 2.
5. **Roadmap reordering** — `Shift+Up` / `Shift+Down` on root todo rows in Preparation view to reorder items in the roadmap.
6. **Prior delivery audit** — Verify all 12 success criteria from `tui-footer-key-contract-restoration` still pass; document and fix gaps.

### Out of scope

- New modal features beyond sizing.
- Footer layout restructuring (3-row layout is stable).
- Agent pill behavior changes.
- Pane theming logic changes (only the `key_display` for `t`).

## Success Criteria

- [ ] SC-1: `NewProjectModal` renders as a compact centered modal (not full-screen); visual height scales to its 4 fields.
- [ ] SC-2: `StartSessionModal` in path mode renders compact (not full-screen).
- [ ] SC-3: In light mode, Row 1 key indicators render in dark/high-contrast text; labels render in visible gray.
- [ ] SC-4: In dark mode, Row 1 key indicators render in bright/white text; labels render in dimmed gray.
- [ ] SC-5: Row 2 shows `q` Quit, `r` Refresh, `t` Cycle Theme — plain lowercase letters, no unicode symbols.
- [ ] SC-6: `a` key cycles animation mode (off → periodic → party) globally; hint shown in Row 2.
- [ ] SC-7: TTS toggle has a keyboard shortcut (prefer `s`, fallback to `v` if `s` conflicts); hint shown in Row 2.
- [ ] SC-8: On root todo rows in Preparation view, `Shift+Up` moves the todo one position up in the roadmap.
- [ ] SC-9: On root todo rows in Preparation view, `Shift+Down` moves the todo one position down in the roadmap.
- [ ] SC-10: `Shift+↑` / `Shift+↓` hints appear in Row 1 only when a root todo row is selected.
- [ ] SC-11: Roadmap reordering calls `telec roadmap move` and rebuilds the tree to reflect new order.
- [ ] SC-12: All 12 success criteria from `tui-footer-key-contract-restoration` still pass (regression check).
- [ ] SC-13: Tests pass (`make test`), lint passes (`make lint`).

## Constraints

- Reuse existing `_format_binding_item()` — extend styling, don't restructure the method.
- Reuse existing `telec roadmap move` CLI — no new roadmap manipulation logic.
- `check_action()` gating pattern must be used for `Shift+Up`/`Shift+Down` (only on root TodoRow).
- If `s` for TTS creates an irreconcilable Textual key-dispatch conflict with `start_work` in Preparation view, use `v` (voice) instead and document the decision.

## Risks

- Textual binding priority: a view-level binding for `s` gated off by `check_action(return False)` may still consume the key event, preventing app-level `s` from firing. Mitigation: builder investigates Textual dispatch before committing to `s`; fallback to `v`.
- `Shift+Up`/`Shift+Down` may conflict with Textual's built-in tree widget scroll. Mitigation: test key capture; override at view level if needed.
