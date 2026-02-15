# TUI Config Experience — Implementation Plan

## Overview

Seven phases, executed sequentially. Phase 1 (creative) must complete before any build phase. Phases 2-6 are build phases with incremental delivery. Phase 7 is cleanup.

Each build phase is scoped to fit a single AI session.

## Codebase Orientation

### Key Files (Existing)

| File                                       | Role                                                         |
| ------------------------------------------ | ------------------------------------------------------------ |
| `teleclaude/cli/tui/app.py`                | Main TUI app, view switching, animation init                 |
| `teleclaude/cli/tui/widgets/tab_bar.py`    | TabBar with TABS list, render, click handling                |
| `teleclaude/cli/tui/views/base.py`         | BaseView + ScrollableViewMixin                               |
| `teleclaude/cli/tui/views/sessions.py`     | SessionsView (tab 1) — reference for new view                |
| `teleclaude/cli/tui/views/preparation.py`  | PreparationView (tab 2) — reference for new view             |
| `teleclaude/cli/tui/state.py`              | TuiState, IntentType, reduce_state reducer                   |
| `teleclaude/cli/tui/controller.py`         | TuiController, LayoutState derivation                        |
| `teleclaude/cli/tui/animation_engine.py`   | AnimationEngine, priority queuing, double-buffer             |
| `teleclaude/cli/tui/animations/base.py`    | Animation ABC (palette, is_big, update, is_complete)         |
| `teleclaude/cli/tui/animations/general.py` | 15 general animations                                        |
| `teleclaude/cli/tui/animations/agent.py`   | 14 agent-specific animations                                 |
| `teleclaude/cli/tui/animation_colors.py`   | ColorPalette, SpectrumPalette, AgentPalette, PaletteRegistry |
| `teleclaude/cli/tui/animation_triggers.py` | PeriodicTrigger, ActivityTrigger                             |
| `teleclaude/cli/tui/pixel_mapping.py`      | PixelMap: banner/logo grid-to-coordinate mapping             |
| `teleclaude/cli/config_handlers.py`        | ConfigArea, discover_config_areas, validate_all, save/load   |
| `teleclaude/cli/config_menu.py`            | Interactive stdin/stdout config menu (to be replaced)        |
| `teleclaude/cli/onboard_wizard.py`         | Guided onboarding wizard (to be replaced)                    |
| `teleclaude/cli/prompt_utils.py`           | ANSI escape helpers (to be reduced/removed)                  |
| `teleclaude/cli/config_cli.py`             | Agent-facing config CLI (stays as-is)                        |

### Key Files (New)

| File                                                    | Role                                                |
| ------------------------------------------------------- | --------------------------------------------------- |
| `teleclaude/cli/tui/views/configuration.py`             | ConfigurationView (tab 3)                           |
| `teleclaude/cli/tui/config_components/`                 | Package for config section components               |
| `teleclaude/cli/tui/config_components/base.py`          | ConfigComponent base class/protocol                 |
| `teleclaude/cli/tui/config_components/adapters.py`      | Adapter config components (Telegram, Discord, etc.) |
| `teleclaude/cli/tui/config_components/people.py`        | People config component                             |
| `teleclaude/cli/tui/config_components/notifications.py` | Notifications config component                      |
| `teleclaude/cli/tui/config_components/environment.py`   | Environment config component                        |
| `teleclaude/cli/tui/config_components/validate.py`      | Validation component with progress                  |
| `teleclaude/cli/tui/config_components/guidance.py`      | Provider guidance registry (data layer)             |
| `teleclaude/cli/tui/animations/config.py`               | Config section animations (Phase 6)                 |

### Architectural Constraints

- Views emit intents; reducer is the only place that mutates TuiState (tui-state-layout design doc).
- Animation engine uses double-buffering; front buffer for rendering, back buffer for updates.
- Config handlers use atomic YAML write with file locking.
- TabBar.TABS is a class-level list; adding tab 3 requires updating it and all view-switching logic.
- Animation base class takes `is_big: bool` — evolution to target-agnostic requires changing this to a target identifier.

---

## Phase 1: Art Direction

**Goal:** Produce visual specs for every config section before any code is written.

**Team:** Art Director + Artist (creative brainstorming session).

- [x] **Deliverables per config section** (Telegram, Discord, WhatsApp, AI Keys, People, Notifications, Environment, Validate):
  - Idle animation concept (subtle, alive, non-distracting)
  - Interaction animation (response to typing/selecting)
  - Success celebration (validation pass)
  - Error/warning state (validation fail)
  - Color palette with hex values and curses color pair mapping
  - ASCII art assets (borders, decorative elements)
- [x] **Deliverables for TUI-wide evolution:**
  - Tab transition animation concept (scroll-out/in, motion)
  - Depth-layered rendering concept (z-order for overlapping)
  - Three-mode toggle behavior (off: static, periodic: current+enhanced, party: maximum energy)

**Stored as:** `todos/tui-config-experience/visual-specs/` directory with per-section specs.

**Exit criteria:** Art director approves final direction as coherent with house style.

---

## Phase 2: Animation Engine Evolution

**Goal:** Make the engine target-agnostic, state-driven, and capable of continuous idle animations.

**Estimated scope:** ~400 lines changed/added across 5 files.

### Step 2.1: Target-Agnostic Rendering

**File:** `animation_engine.py`

- [x] Replace `_big_animation` / `_small_animation` with a `dict[str, AnimationSlot]` keyed by target name.
- [x] `AnimationSlot` holds: animation, frame_count, last_update_ms, priority, queue.
- [x] Replace `_colors_front` / `_colors_back` with `dict[str, dict[tuple[int,int], int]]` per target.
- [x] Update `play(animation, priority, target="banner")` to accept target name.
- [x] Update `update()` to iterate all active targets.
- [x] Update `get_color(x, y, target="banner")` to read from target-specific front buffer.
- [x] Maintain backward compatibility: `is_big=True` maps to target `"banner"`, `is_big=False` maps to target `"logo"`.

**File:** `animations/base.py`

- [x] Add `target: str` field alongside `is_big` (deprecated but kept for compatibility).
- [x] Existing animations continue to work via `is_big` → target mapping.

**File:** `pixel_mapping.py`

- [x] Add `register_target(name, width, height, letters)` for dynamic target registration.
- [x] Existing `BIG_BANNER_*` / `LOGO_*` constants become the "banner" and "logo" targets.
- [x] Config banner zone registers as a new target when the Config tab activates.

### Step 2.2: State-Driven Trigger

**File:** `animation_triggers.py`

- [x] Add `StateDrivenTrigger` class alongside PeriodicTrigger and ActivityTrigger.
- [x] Interface: `set_context(target, section_id, state, progress)` — called by the active config component.
- [x] Trigger selects animation from a registry keyed by `(section_id, state)`.
- [x] Idle state starts continuous animation; interacting/success/error are time-limited.
- [x] Falls back to a default animation if no section-specific one is registered.

### Step 2.3: Section-Aware Palettes

**File:** `animation_colors.py`

- [x] Add `SectionPalette(section_name, colors)` extending `ColorPalette`.
- [x] Register section palettes in `PaletteRegistry`: discord (indigo/blurple), telegram (blue), ai_keys (green/gold), etc.
- [x] Palette colors defined by Phase 1 visual specs.

### Step 2.4: Continuous Idle Animations

**File:** `animation_engine.py`

- [x] Add `looping: bool` flag to `AnimationSlot`.
- [x] When `looping=True`, animation restarts from frame 0 after completion instead of stopping.
- [x] `StateDrivenTrigger` sets `looping=True` for idle state.

### Step 2.5: Three-Mode Toggle

**File:** `teleclaude/cli/tui/app.py` + RuntimeSettings integration

- [x] Add `animation_mode: Literal["off", "periodic", "party"]` to RuntimeSettings (TuiState).
- [x] "off": `animation_engine.is_enabled = False`.
- [x] "periodic": current behavior (PeriodicTrigger + ActivityTrigger active).
- [x] "party": all triggers active, periodic interval reduced to 10s, state-driven idle always active.
- [x] Toggle keybinding in TUI footer (cycle through modes).
- [x] Persist to `~/.teleclaude/tui_state.json`.

### Step 2.6: Scroll/Motion and Depth Layering

- [x] **Defer to Phase 6.** These are visual polish that depend on having config animations to test with. Placeholder hooks are sufficient in Phase 2.

**Verification:** Existing Sessions/Preparation tab animations still work identically. New target registration works. State-driven trigger can be called programmatically.

---

## Phase 3: Config Tab Structure

**Goal:** Working Config tab with sub-tab navigation and placeholder content.

**Estimated scope:** ~500 lines new code across 4 files.

### Step 3.1: Add Tab to TabBar

**File:** `widgets/tab_bar.py`

- [x] Add `(3, "[3] Configuration")` to `TabBar.TABS`.
- [x] No other changes needed — render logic iterates TABS dynamically.

### Step 3.2: Create ConfigurationView

**File:** `views/configuration.py` (new)

- [x] Extend `BaseView`.
- [x] Constructor takes same dependencies as other views: api, agent_availability, focus, pane_manager, state, controller.
- [x] Internal state: `active_subtab: str` (adapters|people|notifications|environment|validate).
- [x] Sub-tab bar rendered below the main tab bar (single row, horizontal labels).
- [x] Content area delegates to the active config component.
- [x] Implements `render()`, `handle_key()`, `handle_click()`, `get_action_bar()`.
- [x] Tab/Shift-Tab cycles sub-tabs; arrow keys navigate within the active component.

### Step 3.3: Add ConfigViewState to TuiState

**File:** `state.py`

- [x] Add `ConfigViewState` dataclass with: `active_subtab`, `selected_field_index`, `scroll_offset`, `guided_mode: bool`.
- [x] Add to `TuiState`: `config: ConfigViewState`.
- [x] Add reducer intents: `SET_CONFIG_SUBTAB`, `SET_CONFIG_FIELD`, `SET_CONFIG_GUIDED_MODE`.

### Step 3.4: Wire into TelecApp

**File:** `app.py`

- [x] Import and instantiate `ConfigurationView` as `self.views[3]`.
- [x] Add key handler for '3' key → `_switch_view(3)`.
- [x] Register config banner target with animation engine when Config tab is active.

### Step 3.5: Provider Guidance Registry

**File:** `config_components/guidance.py` (new)

- [x] Dataclass `FieldGuidance`: description, steps (list[str]), url, format_example, validation_hint.
- [x] Registry: `dict[str, FieldGuidance]` keyed by field path (e.g., "adapters.telegram.bot_token").
- [x] Populated from config_handlers' existing `_ADAPTER_ENV_VARS` registry + additional data.

**Verification:** Tab 3 appears, sub-tab switching works, placeholder content renders. Animation engine receives config banner target context.

---

## Phase 4: Config Components

**Goal:** Fully functional config forms for each section.

**Estimated scope:** ~800 lines across 7 files.

### Step 4.1: ConfigComponent Base

**File:** `config_components/base.py` (new)

- [x] Protocol/ABC with: `render(stdscr, start_row, height, width)`, `handle_key(key)`, `get_section_id() -> str`, `get_animation_state() -> str`, `get_progress() -> float`.
- [x] Manages field list, selected field, input mode (browsing vs editing).
- [x] Calls `config_handlers` for reads/writes.
- [x] Emits animation context changes via callback.

### Step 4.2: Adapter Components

**File:** `config_components/adapters.py` (new)

- [x] `TelegramConfigComponent` — fields from `_ADAPTER_ENV_VARS["telegram"]` + YAML config.
- [x] `DiscordConfigComponent` — Discord bot token, guild ID, channel mappings.
- [x] `WhatsAppConfigComponent` — placeholder (adapter not yet implemented).
- [x] `AIKeysConfigComponent` — Anthropic, OpenAI, Google, ElevenLabs API keys.
- [x] Each component renders: section header, field list with labels/values/status, guidance panel for selected field.
- [x] Input: Enter to edit field, Esc to cancel, field-level validation on confirm.

### Step 4.3: People, Notifications, Environment Components

**Files:** `config_components/people.py`, `notifications.py`, `environment.py` (new)

- [x] People: list view of PersonEntry items, add/edit/remove.
- [x] Notifications: notification channel config.
- [x] Environment: env var status display and guidance (read-only — env vars set in shell, not YAML).

### Step 4.4: Validate Component

**File:** `config_components/validate.py` (new)

- [x] Runs `validate_all()` + `check_env_vars()`.
- [x] Displays progress bar (0.0-1.0) while running.
- [x] Shows per-area pass/fail with error details and suggestions.
- [x] Triggers success celebration or error animation via animation hookpoint.

**Verification:** Each config section renders its fields, accepts input, validates, and saves. Guidance panel shows relevant help. Validation runs end-to-end.

---

## Phase 5: Onboard Integration

**Goal:** `telec onboard` uses the TUI Config tab in guided mode.

**Estimated scope:** ~150 lines changed across 3 files.

### Step 5.1: Guided Mode in ConfigurationView

**File:** `views/configuration.py`

- [x] When `guided_mode=True`, sub-tabs advance sequentially on section completion.
- [x] "Next" / "Skip" controls at bottom of each section.
- [x] Progress indicator: "Step 2 of 5: People".
- [x] At end, show summary + next-steps (matching current wizard behavior).

### Step 5.2: Redirect `telec onboard`

**File:** `teleclaude/cli/helpers/agent_cli.py` or relevant CLI entry point

- [x] `telec onboard` → launch TUI with `--config-guided` flag.
- [x] Flag sets `guided_mode=True` in ConfigViewState before TUI loop starts.
- [x] Detect existing config state via `detect_wizard_state()` to skip completed sections.

**Verification:** `telec onboard` launches TUI in guided mode. Completed sections are skipped. Sequential progression works.

---

## Phase 6: Animation Art

**Goal:** Implement Phase 1 visual specs as animation code.

**Estimated scope:** ~600 lines in new animation file + integration.

### Step 6.1: Section-Specific Animations

**File:** `animations/config.py` (new)

- [x] Implement idle, interaction, success, error animations per section from visual specs.
- [x] Register in state-driven trigger registry keyed by `(section_id, state)`.

### Step 6.2: Tab Transition Animations

- [ ] Scroll-out/in motion on tab switches.
- [ ] Integrated into `_switch_view()` in app.py.

### Step 6.3: Celebration Effects

- [x] Validation success: multi-stage celebration animation.
- [x] Wired to Validate component's success state.

### Step 6.4: Depth-Layered Rendering (if in scope from Phase 1)

- [ ] Z-order rendering for overlapping animation elements.
- [ ] Applied to Sessions/Preparation tabs as well (behind active tab, in front of inactive).

**Verification:** Each config section plays its idle animation. Interactions trigger visual response. Validation celebrations fire. Tab transitions are smooth.

---

## Phase 7: Cleanup

**Goal:** Remove dead code, update CLI help.

**Estimated scope:** ~200 lines removed, ~20 lines changed.

### Step 7.1: Remove Old Files

- [x] Delete `teleclaude/cli/config_menu.py`.
- [x] Delete `teleclaude/cli/onboard_wizard.py`.
- [x] Audit `teleclaude/cli/prompt_utils.py` — remove if fully unused, or strip to minimal headless fallback.

### Step 7.2: Update CLI Entry Points

- [x] `telec config` (no subcommand) → launch TUI Config tab.
- [x] `telec config get/patch/validate` → unchanged.
- [x] `telec onboard` → launch TUI guided mode.
- [x] Update `--help` text for both commands.

### Step 7.3: Test Pass

- [x] Verify all existing TUI tests pass.
- [x] Verify config CLI agent commands still work.
- [x] Verify `telec onboard` guided flow end-to-end.

**Verification:** No dead imports, no orphaned files. CLI help is accurate. Tests pass.

---

## Risk Register

| Risk                                                                | Mitigation                                                                        |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Phase 1 creative output may be too ambitious for curses constraints | Art director enforces feasibility; prototype key animations early                 |
| Animation engine refactor breaks existing animations                | Phase 2 backward-compat mapping (is_big → target); test existing animations first |
| Config tab scope creep from rich form interactions                  | Start with simple field-per-line forms; enhance iteratively                       |
| Session-size risk for Phase 4 (most components)                     | Split adapter components across two sessions if needed                            |
| Curses input handling complexity for form editing                   | Reuse patterns from existing views; keep input modes minimal (browse/edit)        |
