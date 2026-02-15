# TUI Config Experience — Requirements

## Problem Statement

Configuration is split across two throwaway CLI tools (`telec config` interactive menu, `telec onboard` wizard) that use raw `input()` prompts and hand-rolled ANSI codes. Meanwhile the TUI has a mature curses-based tab system, animation engine, and theme infrastructure. Users get no guidance on where to obtain credentials, no visual feedback on validation, and no connection to the TeleClaude visual identity during setup.

The animation engine is capable but limited to two hardcoded targets (big banner, small logo), random/agent-triggered selection only, and no support for continuous idle animations, state-driven selection, section-aware palettes, scroll/motion transitions, or depth layering.

## Intended Outcome

All interactive configuration lives inside the TUI as a first-class Config tab. Each config section is a reusable curses component with contextual guidance, provider-specific help, and section-aware animation. The animation engine evolves into a target-agnostic, state-driven system that enriches the entire TUI. `telec onboard` becomes a guided-mode entry point into the same Config tab. The old interactive menu and wizard are removed.

## Success Criteria

- SC-1: `telec config` (no subcommand) launches the TUI Config tab instead of the interactive menu.
- SC-2: `telec onboard` launches the TUI in Config tab guided mode.
- SC-3: Every adapter section (Telegram, Discord, WhatsApp, AI Keys), People, Notifications, Environment, and Validate has its own config component with contextual guidance.
- SC-4: Each config section displays provider-specific help: description, numbered steps to obtain credentials, direct URL to provider portal, expected format with example, and validation rules.
- SC-5: The animation engine supports arbitrary render targets beyond big banner and small logo.
- SC-6: Animations can be selected by section + state (idle/interacting/success/error), not only random/agent triggers.
- SC-7: Each config section has a distinct color palette (provider brand colors like Discord blurple, Telegram blue are encouraged for recognition).
- SC-8: Continuous idle animations run while a config section is active without being distracting.
- SC-9: A three-mode animation toggle exists: off / periodic / party.
- SC-10: `telec config get/patch/validate` CLI subcommands for agents remain unchanged.
- SC-11: `config_menu.py`, `onboard_wizard.py`, and unnecessary parts of `prompt_utils.py` are removed.
- SC-12: Visual specs for every config section are designed and approved before builder implementation begins.

## Functional Requirements

### FR-1: Config Tab in TUI

- FR-1.1: Add a third tab `[3] Configuration` to the TUI TabBar.
- FR-1.2: The Config tab has sub-tab navigation for: Adapters, People, Notifications, Environment, Validate.
- FR-1.3: The Adapters sub-tab contains sections for each adapter discovered by `config_handlers.discover_config_areas()` (Telegram, Discord, WhatsApp, AI Keys).
- FR-1.4: Each config section renders as a form with labeled fields, current values, status indicators, and inline validation.
- FR-1.5: Navigation within the Config tab uses arrow keys for field traversal and Tab/Shift-Tab for sub-tab switching.
- FR-1.6: The Config tab consumes `config_handlers.py` for all read/write/validate operations (no duplication of config logic).

### FR-2: Provider Guidance Registry

- FR-2.1: A data-only registry holds rich contextual help for every config field: description, numbered steps, URL, format example, validation rule.
- FR-2.2: The registry is the single source of truth for credential guidance, consumed by both Config tab and guided mode.
- FR-2.3: URLs in guidance are rendered as clickable terminal hyperlinks (OSC 8) where supported.

### FR-3: Config Components

- FR-3.1: Each config section is a self-contained curses component that can render guidance, display current values, accept input with validation, and trigger its section-specific animation.
- FR-3.2: Components share a base class or protocol with a consistent interface: `render()`, `handle_key()`, `get_section_id()`, `get_state()`.
- FR-3.3: The Validate component runs `config_handlers.validate_all()` and `check_env_vars()`, displaying progress and per-area results.
- FR-3.4: Validation success triggers a celebration animation; validation failure triggers an error animation.

### FR-4: Onboard Guided Mode

- FR-4.1: `telec onboard` launches the TUI directly into the Config tab in guided mode.
- FR-4.2: Guided mode steps through sub-tabs sequentially: Adapters -> People -> Notifications -> Environment -> Validate.
- FR-4.3: Guided mode detects existing config and skips completed sections (preserving current `detect_wizard_state()` behavior).
- FR-4.4: At completion, guided mode shows next-steps summary.

### FR-5: Animation Engine Evolution

- FR-5.1: The engine supports named render targets (e.g., "banner", "logo", "config_banner") instead of hardcoded big/small.
- FR-5.2: A new state-driven trigger selects animations based on `(section_id, state)` tuples where state is one of: idle, interacting, success, error.
- FR-5.3: Section-aware palettes are registered in `PaletteRegistry` (e.g., "discord", "telegram", "ai_keys"). Palette design is defined by Phase 1 visual specs.
- FR-5.4: Continuous idle animations run indefinitely until explicitly stopped or replaced (unlike current fire-and-finish model).
- FR-5.5: Scroll/motion transitions animate tab and section switches (scroll-out/in, fade).
- FR-5.6: Depth layering supports z-order for overlapping elements.
- FR-5.7: A three-mode toggle (off / periodic / party) is persisted as a user preference in RuntimeSettings.
- FR-5.8: Existing PeriodicTrigger and ActivityTrigger continue to work for Sessions/Preparation tabs.
- FR-5.9: The animation hookpoint contract provides: target, section_id, state, progress (0.0-1.0).

### FR-6: Cleanup

- FR-6.1: Remove `config_menu.py` (replaced by Config tab).
- FR-6.2: Remove `onboard_wizard.py` (replaced by guided mode).
- FR-6.3: Reduce `prompt_utils.py` to only what's needed for headless/agent fallback (or remove entirely if unused).
- FR-6.4: Update CLI help text for `telec config` and `telec onboard`.

## Visual Style Direction

The aesthetic target for all visual elements — animations, borders, decorative art, section headers, status indicators — is defined here. This is creative direction, not a prohibition list. The Art Director and Artist have full creative freedom within this style.

### Style: 8-Bit / Chiptune Pop

The feel is Commodore 64, early Mario, chiptune — poppy, contrast-rich, alive. Simple shapes that punch. Color that pops against the terminal background. Animations that give the interface personality without overwhelming it.

TeleClaude does not have an established house visual identity beyond the current banner with color cycling. This work defines it. The creative team owns that definition.

### Contrast-Rich

Elements should be clearly visible and distinct. The interface should feel crisp and readable. When something is animated, it should be noticeable. When something is static, it should be clean.

### Simple, Not Spectacle

The banner's current simplicity — text with color cycling — is the starting point. The goal is to extend that into something richer while keeping the same spirit: life and personality, not visual noise.

### Provider Colors Welcome

Section palettes may use provider brand colors (Discord's blurple, Telegram's blue, etc.) for recognition. There is no TeleClaude brand palette to conflict with — the creative team defines what works.

### Banner Area: Make It Fun

The TELECLAUDE banner is not a static logo. It's a playground. The creative team should design scene animations that bring the banner and surrounding TUI to life — not just color cycling, but movement, character, surprise.

**Inspiration (invent more of the same):**

- A tiny character rides a bicycle across the tab pane line — in front of subdued tabs, behind the selected tab (depth/parallax)
- A car drives across the same line in the other direction
- The TELECLAUDE banner scrolls out of the window to the left and comes back in from the right
- The banner drops in from above, lands with a bounce
- The banner disintegrates into pixels and reassembles
- Scrolling banners, marquee text, demoscene-style scrollers

These are examples, not a checklist. The creative team should take this energy and run with it — more playful scene animations, more surprises, more personality. The banner area should make people smile.

## Non-Functional Requirements

- NFR-1: Config tab renders correctly in terminals >= 80 columns wide.
- NFR-2: Animation engine evolution must not break existing banner/logo animations in Sessions and Preparation tabs.
- NFR-3: Config read/write operations use the existing atomic YAML write path (file lock + tmp + replace).
- NFR-4: The creative phase (art direction) produces concrete visual specs before any animation implementation begins.
- NFR-5: All visual output aligns with the Visual Style Direction. The creative team defines what that means concretely.

## Out of Scope

- Changes to `telec config get/patch/validate` programmatic CLI (stays as-is for agents).
- Changes to `config_cli.py` or `config_cmd.py` (agent-facing APIs unchanged).
- WhatsApp adapter implementation (config component is scaffolded, actual adapter is separate work).
- Web interface config (future work).

## Dependencies

- None. This todo owns the full animation evolution and config tab work.

## Absorbs

- `config-visual-polish` — fully absorbed (animated config with section theming).
- `tui-animation-art` — fully absorbed (banner motion, depth layering, animation modes, creative-first process).
