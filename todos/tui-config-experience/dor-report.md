# TUI Config Experience — DOR Report

## Gate Verdict: PASS (score 8/10)

Ready for implementation. One decision recorded below; no hard blockers.

## Gate Analysis

### 1. Intent & Success — PASS

Problem statement and intended outcome are explicit. Twelve success criteria are concrete and testable. The "what" and "why" are thoroughly captured in requirements.md.

### 2. Scope & Size — PASS (with note)

Seven phases, ~2500 LOC, 7+ sessions. This is large but well-structured.

**Decision: keep as one todo.** Phases are sequential with a single dependency chain — splitting into sub-todos would add overhead (7 slugs, 7 state files, dependency wiring) for no scheduling or parallelism benefit. Phase progress is tracked internally via state.json.

Phase 1 (Art Direction) is categorically different (creative, no code), but SC-12 already gates it: "Visual specs designed and approved before builder implementation begins." This is sufficient without a formal split.

### 3. Verification — PASS

Each phase has explicit verification criteria. Edge cases identified: terminal width, animation backward compat, form input modes.

### 4. Approach Known — PASS

All key patterns confirmed in codebase:

- TabBar.TABS is a class-level list at `widgets/tab_bar.py:11` — adding tab 3 is mechanical.
- AnimationEngine at `animation_engine.py:18` uses `_big_animation`/`_small_animation` — evolution path to dict-based targets is clear.
- `config_handlers.py` provides `ConfigArea`, `discover_config_areas()`, `validate_all()` — config components consume these directly.
- `TuiState` at `state.py:74` already has per-view state pattern (`SessionViewState`, `PreparationViewState`) — adding `ConfigViewState` follows the same pattern.
- `RuntimeSettings` at `config/runtime_settings.py:49` uses debounced YAML persistence — animation mode toggle fits this pattern.
- Curses form input: char-by-char handling (same pattern as existing tree interaction), no spike needed.
- Depth layering: explicitly deferred in Phase 2, implemented in Phase 6 only if Phase 1 produces clear specs.

### 5. Research Complete — PASS

No third-party dependencies introduced. All technology is built-in curses + existing engine. OSC 8 hyperlinks are a known terminal protocol with graceful degradation.

### 6. Dependencies & Preconditions — PASS

- `config_handlers.py` exists with full read/write/validate layer (delivered).
- Animation engine exists with double-buffer, priority queue, frame-based updates (delivered).
- `config_menu.py` and `onboard_wizard.py` exist and are the files to be replaced.
- `detect_wizard_state()` exists at `onboard_wizard.py:73` for guided mode skip logic.
- No external blocking dependencies.

### 7. Integration Safety — PASS

- Phase 2 maintains backward compatibility via `is_big` to target name mapping.
- Phases deliver incrementally; each can be verified independently.
- Phase 7 cleanup only removes files after replacements are verified.
- Config CLI agent commands (`get/patch/validate`) remain untouched throughout.

### 8. Tooling Impact — N/A

No changes to scaffolding, CI, or build tooling.

## Resolved Decisions

1. **Splitting:** Keep as one todo. No parallelism benefit from splitting a sequential chain.
2. **Creative phase:** Single brainstorming session (art director + artist agents). SC-12 gates subsequent phases.
3. **Scroll/motion/depth layering:** Deferred to Phase 6, contingent on Phase 1 output. Already stated in implementation plan.
4. **Headless fallback:** `telec config` (no subcommand) in a non-interactive terminal prints an error directing users to `telec config get/patch/validate`. No old-menu fallback.

## Assumptions

1. Curses text input uses simple char-by-char handling (existing pattern), not curses.textpad.
2. Animation mode toggle uses RuntimeSettings persistence (debounced YAML write).
3. WhatsApp config component is a placeholder (adapter not implemented).
4. Phase 1 visual specs are stored as documents in `todos/tui-config-experience/visual-specs/`.
