# tui-config-experience

Move all interactive configuration into the TUI as a first-class Config tab with sub-tabs, killing the ugly standalone `telec config` interactive menu and `telec onboard` CLI wizard. Each config section becomes a reusable component (curses view) with contextual guidance, provider-specific help with links, and its own section-aware animation. `telec onboard` becomes "launch the TUI in Config tab, guided mode" using the same components.

## Vision

Configuration should be joyful, not tedious. The current `telec config` and `telec onboard` are raw `input()` prompts with hand-rolled ANSI codes — functional but ugly, zero guidance, no visual identity. Meanwhile we have a beautiful curses TUI with tabs, themes, and an animation system. Configuration belongs inside that world, not in a throwaway CLI experience.

Every config section gets its own animation in the banner zone above the form. Commodore 64 demoscene meets modern terminal art. Section-aware theming: Discord section gets its own visual mood, Telegram gets another, validation success triggers a celebration. The animations are not decoration — they're identity. They communicate "you're in the Discord section" before the user reads a word.

## Creative Brief

This work has a **creative phase before the build phase**. The animations, visual language, and section theming must be designed collaboratively before any builder touches code.

**Art Director role:** Ensures visual coherence with our house style (C64/retro-gaming aesthetic from the existing banner animation system). Makes decisions about what aligns, what doesn't. Filters artist proposals through the lens of: does this feel like TeleClaude?

**Artist role:** Goes broad — proposes animation concepts, color palettes, transition effects, idle animations, interaction responses for each config section. Explores freely within the retro-gaming space. Produces concrete visual specs (ASCII art frames, color schemes, animation timing).

**The creative output** (before build begins): A visual spec per config section defining:

- Idle animation (what plays while the user reads/thinks)
- Interaction animation (what happens when the user inputs/saves)
- Celebration animation (what happens on successful validation)
- Color palette / theme for the section
- Any pixel art / ASCII art assets

Creative freedom is the point. The AIs working on this should brainstorm, propose, critique, and refine — not execute a rigid spec. The art director ensures alignment; the artists push boundaries.

## Architecture

### What's new

```
telec (TUI)
  +-- Config tab (NEW)
        +-- Adapters sub-tab
        |     +-- Telegram (form + guidance + animation)
        |     +-- Discord (form + guidance + animation)
        |     +-- WhatsApp (form + guidance + animation)
        |     +-- AI Keys (form + guidance + animation)
        +-- People sub-tab (form + guidance + animation)
        +-- Notifications sub-tab (form + guidance + animation)
        +-- Environment sub-tab (form + guidance + animation)
        +-- Validate sub-tab (progress + celebration animation)
```

### What dies

- `telec config` interactive menu (`config_menu.py`) — replaced by Config tab
- `telec onboard` wizard (`onboard_wizard.py`) — replaced by guided mode through Config tab
- `prompt_utils.py` — replaced by TUI components (or reduced to fallback for headless environments)
- All hand-rolled ANSI escape code rendering in config flows

### What stays

- `telec config get/patch/validate` — programmatic CLI for agents and scripts (no UI, stays as-is)
- `telec config people/env/notify` — agent-facing API (no UI, stays as-is)
- `config_handlers.py` — read/write/validate layer, now consumed by TUI components
- `config_cli.py` — agent-facing CLI API

### Config components

Each config section is a self-contained curses view that knows how to:

1. Render contextual guidance (what this field is, where to get it, what format, with links)
2. Display current values and status
3. Accept input with validation
4. Show its section-specific animation in the banner zone

These components are the same ones used by both the Config tab (free navigation) and the onboard guided mode (sequential walk-through).

### Provider guidance registry

A data layer (not UI) that holds rich contextual help for every credential/config field:

- Description: what this field does
- Steps: numbered instructions to obtain the value
- URL: direct link to the provider's portal/dashboard
- Format: expected format with example
- Validation: what makes a value valid

This registry is consumed by the TUI config components. It's the single source of truth for "how do I get a Discord bot token?" — shared across all paths.

### Onboard guided mode

`telec onboard` launches the TUI directly into the Config tab in guided mode:

- Steps through sub-tabs sequentially (Adapters -> People -> Notifications -> Environment -> Validate)
- Detects existing config and skips completed sections (existing behavior, preserved)
- Same components, same animations — just a different traversal pattern
- At the end, shows next steps (same as current wizard)

### Animation hookpoint contract

Each config sub-tab provides a banner zone (top N rows) to the animation system. The animation system receives:

- `section_id`: which config section is active (e.g., "discord", "telegram", "validate")
- `state`: idle / interacting / success / error
- `progress`: 0.0-1.0 for validation progress

The animation renderer is a callback that the config tab calls on each refresh. This is the contract that `tui-animation-art` fulfills — this todo defines the integration surface, not the animation implementation itself.

## Phased Execution

### Phase 1: Art Direction (team: art director + artist)

- Brainstorm visual concepts per config section
- Define house style rules for config animations
- Produce visual spec with ASCII art frames, palettes, timing
- Art director approves final direction

### Phase 2: Build — Config Tab Structure

- New Config tab in TUI with sub-tab navigation
- Provider guidance registry (data layer)
- Config component base class / pattern
- Animation hookpoint contract (banner zone integration)

### Phase 3: Build — Config Components

- Adapter components (Telegram, Discord, WhatsApp, AI Keys) with guidance
- People component
- Notifications component
- Environment component
- Validate component with progress

### Phase 4: Build — Onboard Integration

- `telec onboard` redirects to TUI guided mode
- Sequential traversal through config components
- Skip-completed-sections detection

### Phase 5: Build — Animation Integration

- Connect Phase 1 visual specs to animation hookpoints
- Section-aware theming
- Celebration effects on validation success

### Phase 6: Cleanup

- Remove `config_menu.py`
- Remove `onboard_wizard.py`
- Remove or reduce `prompt_utils.py`
- Update `telec config -h` and `telec onboard -h`

## Absorbs

- `config-visual-polish` — fully absorbed (animated config with section theming)
- Partially overlaps with `tui-animation-art` — the animation hookpoint and section-aware rendering are defined here; the broader TUI animation system remains its own todo

## Dependencies

- `after: tui-animation-art` (for the animation infrastructure, but Phase 1-4 can start in parallel)
