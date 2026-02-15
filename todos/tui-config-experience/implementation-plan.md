# TUI Config Experience — Implementation Plan

## Overview

Seven phases. Phase 1 (creative) must complete before any build phase. After Phase 2, build work splits into two parallel tracks. Phase 7 is cleanup after both tracks complete.

Each build phase is scoped to fit a single AI session.

## Team Structure

| Phase      | Team                              | Role                                                                                                                                                                                                                                                                             |
| ---------- | --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Phase 1    | Art Director + Artist + Builder B | Creative workshop. Art Director curates, Artist generates, Builder B provides technical grounding and helps write prototype code against the Animation ABC. All three collaborate — the builder is not a spectator, they ensure prototypes are grounded in the engine's reality. |
| Phase 2    | Builder A                         | Engine evolution. Makes the architecture ready for everything that follows.                                                                                                                                                                                                      |
| Phases 3–5 | Builder A                         | Config tab structure, components, onboarding. Serial dependency chain.                                                                                                                                                                                                           |
| Phase 6    | Builder B                         | Animation art integration. Builder B was in the creative phase — they have full context on creative intent. They integrate the prototype artifacts without reinterpreting them.                                                                                                  |
| Phase 7    | Whoever finishes last             | Cleanup. Trivial.                                                                                                                                                                                                                                                                |

**Why this split:** Phases 3–5 and Phase 6 are independent after Phase 2 completes. Builder A handles the structural/architectural track (config tab, components, onboarding). Builder B handles the creative integration track (animations, scenes, depth layering). Builder B MUST be the same agent who participated in Phase 1 — they carry the creative context that eliminates translation loss.

```
Phase 1 (creative team)
    │
    ▼
Phase 2 (Builder A — engine evolution)
    │
    ├──────────────────────┐
    ▼                      ▼
Phase 3 (Builder A)    Phase 6 (Builder B)
    │                  animation integration
    ▼
Phase 4 (Builder A)
    │
    ▼
Phase 5 (Builder A)
    │                      │
    └──────────┬───────────┘
               ▼
         Phase 7 (cleanup)
```

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

**Team:** Art Director + Artist + Builder B (creative workshop — all three collaborate).

**Style Direction:** 8-bit / Commodore 64 / chiptune pop aesthetic. Contrast-rich, poppy, alive. Simple and purposeful — personality without visual noise. Provider brand colors welcome for recognition. The creative team has full freedom within this style. See Visual Style Direction in requirements.md.

**Deliverables per config section** (Telegram, Discord, WhatsApp, AI Keys, People, Notifications, Environment, Validate):

- Idle animation concept (subtle, alive, non-distracting)
- Interaction animation (response to typing/selecting)
- Success celebration (validation pass)
- Error/warning state (validation fail)
- Color palette with xterm-256 color values and curses color pair mapping
- ASCII art assets (borders, decorative elements)

**Deliverables for banner scene animations:**

- Playful scene animation concepts for the main banner area — characters, objects, movement with depth layering (see "Banner Area: Make It Fun" in requirements.md for inspiration)
- Banner entrance/exit animations (scroll out, drop in, disintegrate, reassemble, marquee)
- Depth-layered scene concepts: objects that pass in front of subdued tabs but behind the selected tab, creating parallax
- Invent more. These are pointers — the creative team should surprise us.

**Deliverables for TUI-wide evolution:**

- Tab transition animation concept (scroll-out/in, motion)
- Depth-layered rendering concept (z-order for overlapping)
- Three-mode toggle behavior (off: static, periodic: current+enhanced, party: maximum energy)

**Artifact format (stored in `todos/tui-config-experience/visual-specs/`):**

The creative team produces working prototypes, not prose-only specs. This eliminates translation loss between creative and build phases.

Per config section:

- `{section}.md` — concept doc: mood, creative intent, why this animation fits, color rationale
- `{section}_animations.py` — prototype Animation subclasses extending the existing ABC (`animations/base.py`). Uses `PixelMap`, returns `Dict[Tuple[int,int], int]` from `update()`. Working code, not production quality — creative sketches that run.
- `{section}_palette.py` — palette definition with xterm-256 color values, structured for `PaletteRegistry`

TUI-wide:

- `banner_scenes.md` — concept doc for banner scene animations
- `banner_scenes.py` — prototype scene animations (character movement, entrance/exit, parallax depth)
- `transitions.md` — tab transition and depth layering concepts
- `animation_modes.md` — three-mode toggle behavior spec (off / periodic / party)

**Why prototype code:** AI agents can write Python. Prose descriptions of animations create ambiguity ("gentle breathing" means different things). Working prototype code IS the animation — frame by frame, color by color. The builder integrates without reinterpreting.

**Exit criteria:** Art director approves final direction as coherent across all sections. Prototype animations run against the existing Animation ABC.

---

## Phase 2: Animation Engine Evolution

**Assigned to:** Builder A

**Goal:** Make the engine target-agnostic, state-driven, and capable of continuous idle animations.

**Estimated scope:** ~400 lines changed/added across 5 files.

### Step 2.1: Target-Agnostic Rendering

**File:** `animation_engine.py`

- Replace `_big_animation` / `_small_animation` with a `dict[str, AnimationSlot]` keyed by target name.
- `AnimationSlot` holds: animation, frame_count, last_update_ms, priority, queue.
- Replace `_colors_front` / `_colors_back` with `dict[str, dict[tuple[int,int], int]]` per target.
- Update `play(animation, priority, target="banner")` to accept target name.
- Update `update()` to iterate all active targets.
- Update `get_color(x, y, target="banner")` to read from target-specific front buffer.
- Maintain backward compatibility: `is_big=True` maps to target `"banner"`, `is_big=False` maps to target `"logo"`.

**File:** `animations/base.py`

- Add `target: str` field alongside `is_big` (deprecated but kept for compatibility).
- Existing animations continue to work via `is_big` → target mapping.

**File:** `pixel_mapping.py`

- Add `register_target(name, width, height, letters)` for dynamic target registration.
- Existing `BIG_BANNER_*` / `LOGO_*` constants become the "banner" and "logo" targets.
- Config banner zone registers as a new target when the Config tab activates.

### Step 2.2: State-Driven Trigger

**File:** `animation_triggers.py`

- Add `StateDrivenTrigger` class alongside PeriodicTrigger and ActivityTrigger.
- Interface: `set_context(target, section_id, state, progress)` — called by the active config component.
- Trigger selects animation from a registry keyed by `(section_id, state)`.
- Idle state starts continuous animation; interacting/success/error are time-limited.
- Falls back to a default animation if no section-specific one is registered.

### Step 2.3: Section-Aware Palettes

**File:** `animation_colors.py`

- Add `SectionPalette(section_name, colors)` extending `ColorPalette`.
- Register section palettes in `PaletteRegistry` as defined by Phase 1 visual specs.
- Palette design (colors, structure) is owned by the creative team.

### Step 2.4: Continuous Idle Animations

**File:** `animation_engine.py`

- Add `looping: bool` flag to `AnimationSlot`.
- When `looping=True`, animation restarts from frame 0 after completion instead of stopping.
- `StateDrivenTrigger` sets `looping=True` for idle state.

### Step 2.5: Three-Mode Toggle

**File:** `teleclaude/cli/tui/app.py` + RuntimeSettings integration

- Add `animation_mode: Literal["off", "periodic", "party"]` to RuntimeSettings.
- "off": `animation_engine.is_enabled = False`.
- "periodic": current behavior (PeriodicTrigger + ActivityTrigger active).
- "party": all triggers active, periodic interval reduced to 10s, state-driven idle always active.
- Toggle keybinding in TUI footer (cycle through modes).
- Persist to `~/.teleclaude/tui_state.json`.

### Step 2.6: Scroll/Motion and Depth Layering

- **Defer to Phase 6.** These are visual polish that depend on having config animations to test with. Placeholder hooks are sufficient in Phase 2.

**Verification:** Existing Sessions/Preparation tab animations still work identically. New target registration works. State-driven trigger can be called programmatically.

---

## Phase 3: Config Tab Structure

**Assigned to:** Builder A (starts after Phase 2, runs parallel with Phase 6)

**Goal:** Working Config tab with sub-tab navigation and placeholder content.

**Estimated scope:** ~500 lines new code across 4 files.

### Step 3.1: Add Tab to TabBar

**File:** `widgets/tab_bar.py`

- Add `(3, "[3] Configuration")` to `TabBar.TABS`.
- No other changes needed — render logic iterates TABS dynamically.

### Step 3.2: Create ConfigurationView

**File:** `views/configuration.py` (new)

- Extend `BaseView`.
- Constructor takes same dependencies as other views: api, agent_availability, focus, pane_manager, state, controller.
- Internal state: `active_subtab: str` (adapters|people|notifications|environment|validate).
- Sub-tab bar rendered below the main tab bar (single row, horizontal labels).
- Content area delegates to the active config component.
- Implements `render()`, `handle_key()`, `handle_click()`, `get_action_bar()`.
- Tab/Shift-Tab cycles sub-tabs; arrow keys navigate within the active component.

### Step 3.3: Add ConfigViewState to TuiState

**File:** `state.py`

- Add `ConfigViewState` dataclass with: `active_subtab`, `selected_field_index`, `scroll_offset`, `guided_mode: bool`.
- Add to `TuiState`: `config: ConfigViewState`.
- Add reducer intents: `SET_CONFIG_SUBTAB`, `SET_CONFIG_FIELD`, `SET_CONFIG_GUIDED_MODE`.

### Step 3.4: Wire into TelecApp

**File:** `app.py`

- Import and instantiate `ConfigurationView` as `self.views[3]`.
- Add key handler for '3' key → `_switch_view(3)`.
- Register config banner target with animation engine when Config tab is active.

### Step 3.5: Provider Guidance Registry

**File:** `config_components/guidance.py` (new)

- Dataclass `FieldGuidance`: description, steps (list[str]), url, format_example, validation_hint.
- Registry: `dict[str, FieldGuidance]` keyed by field path (e.g., "adapters.telegram.bot_token").
- Populated from config_handlers' existing `_ADAPTER_ENV_VARS` registry + additional data.

**Verification:** Tab 3 appears, sub-tab switching works, placeholder content renders. Animation engine receives config banner target context.

---

## Phase 4: Config Components

**Assigned to:** Builder A

**Goal:** Fully functional config forms for each section.

**Estimated scope:** ~800 lines across 7 files.

### Step 4.1: ConfigComponent Base

**File:** `config_components/base.py` (new)

- Protocol/ABC with: `render(stdscr, start_row, height, width)`, `handle_key(key)`, `get_section_id() -> str`, `get_animation_state() -> str`, `get_progress() -> float`.
- Manages field list, selected field, input mode (browsing vs editing).
- Calls `config_handlers` for reads/writes.
- Emits animation context changes via callback.

### Step 4.2: Adapter Components

**File:** `config_components/adapters.py` (new)

- `TelegramConfigComponent` — fields from `_ADAPTER_ENV_VARS["telegram"]` + YAML config.
- `DiscordConfigComponent` — Discord bot token, guild ID, channel mappings.
- `WhatsAppConfigComponent` — placeholder (adapter not yet implemented).
- `AIKeysConfigComponent` — Anthropic, OpenAI, Google, ElevenLabs API keys.
- Each component renders: section header, field list with labels/values/status, guidance panel for selected field.
- Input: Enter to edit field, Esc to cancel, field-level validation on confirm.

### Step 4.3: People, Notifications, Environment Components

**Files:** `config_components/people.py`, `notifications.py`, `environment.py` (new)

- People: list view of PersonEntry items, add/edit/remove.
- Notifications: notification channel config.
- Environment: env var status display and guidance (read-only — env vars set in shell, not YAML).

### Step 4.4: Validate Component

**File:** `config_components/validate.py` (new)

- Runs `validate_all()` + `check_env_vars()`.
- Displays progress bar (0.0-1.0) while running.
- Shows per-area pass/fail with error details and suggestions.
- Triggers success celebration or error animation via animation hookpoint.

**Verification:** Each config section renders its fields, accepts input, validates, and saves. Guidance panel shows relevant help. Validation runs end-to-end.

---

## Phase 5: Onboard Integration

**Assigned to:** Builder A

**Goal:** `telec onboard` uses the TUI Config tab in guided mode.

**Estimated scope:** ~150 lines changed across 3 files.

### Step 5.1: Guided Mode in ConfigurationView

**File:** `views/configuration.py`

- When `guided_mode=True`, sub-tabs advance sequentially on section completion.
- "Next" / "Skip" controls at bottom of each section.
- Progress indicator: "Step 2 of 5: People".
- At end, show summary + next-steps (matching current wizard behavior).

### Step 5.2: Redirect `telec onboard`

**File:** `teleclaude/cli/helpers/agent_cli.py` or relevant CLI entry point

- `telec onboard` → launch TUI with `--config-guided` flag.
- Flag sets `guided_mode=True` in ConfigViewState before TUI loop starts.
- Detect existing config state via `detect_wizard_state()` to skip completed sections.

**Verification:** `telec onboard` launches TUI in guided mode. Completed sections are skipped. Sequential progression works.

---

## Phase 6: Animation Art Integration

**Assigned to:** Builder B (starts after Phase 2, runs parallel with Phases 3–5)

**Goal:** Integrate Phase 1 creative artifacts into the production animation system.

**Input:** `todos/tui-config-experience/visual-specs/` — prototype Animation subclasses, palette definitions, scene animations, concept docs.

**Estimated scope:** ~600 lines in new animation file + integration.

**Why Builder B:** This builder participated in the Phase 1 creative workshop. They know the creative intent firsthand — they helped write the prototype code. No translation loss. They take their own prototypes and make them production-ready inside the engine.

### Step 6.1: Section-Specific Animations

**File:** `animations/config.py` (new)

- Integrate prototype animations from `visual-specs/{section}_animations.py` into production Animation subclasses.
- Register in state-driven trigger registry keyed by `(section_id, state)`.
- Integrate palette definitions from `visual-specs/{section}_palette.py` into PaletteRegistry.

### Step 6.2: Banner Scene Animations

- Integrate prototype scene animations from `visual-specs/banner_scenes.py`.
- Character movement, entrance/exit animations, depth-layered parallax.
- These run across all tabs, not just Config.

### Step 6.3: Tab Transition Animations

- Scroll-out/in motion on tab switches.
- Integrated into `_switch_view()` in app.py.

### Step 6.4: Celebration Effects

- Validation success: multi-stage celebration animation.
- Wired to Validate component's success state.

### Step 6.5: Depth-Layered Rendering

- Z-order rendering for overlapping animation elements.
- Applied to Sessions/Preparation tabs as well (behind active tab, in front of inactive).
- Scene animations use depth: objects pass in front of subdued tabs, behind selected tab.

**Verification:** Each config section plays its idle animation. Interactions trigger visual response. Validation celebrations fire. Tab transitions are smooth. Banner scenes play with correct depth layering.

---

## Phase 7: Cleanup

**Assigned to:** Whoever finishes last (Builder A or Builder B)

**Goal:** Remove dead code, update CLI help.

**Estimated scope:** ~200 lines removed, ~20 lines changed.

### Step 7.1: Remove Old Files

- Delete `teleclaude/cli/config_menu.py`.
- Delete `teleclaude/cli/onboard_wizard.py`.
- Audit `teleclaude/cli/prompt_utils.py` — remove if fully unused, or strip to minimal headless fallback.

### Step 7.2: Update CLI Entry Points

- `telec config` (no subcommand) → launch TUI Config tab.
- `telec config get/patch/validate` → unchanged.
- `telec onboard` → launch TUI guided mode.
- Update `--help` text for both commands.

### Step 7.3: Test Pass

- Verify all existing TUI tests pass.
- Verify config CLI agent commands still work.
- Verify `telec onboard` guided flow end-to-end.

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
