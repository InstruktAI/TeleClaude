# tui-config-experience

Move all interactive configuration into the TUI as a first-class Config tab with sub-tabs, killing the ugly standalone `telec config` interactive menu and `telec onboard` CLI wizard. Each config section becomes a reusable component (curses view) with contextual guidance, provider-specific help with links, and its own section-aware animation. `telec onboard` becomes "launch the TUI in Config tab, guided mode" using the same components.

## Vision

Configuration should be joyful, not tedious. The current `telec config` and `telec onboard` are raw `input()` prompts with hand-rolled ANSI codes — functional but ugly, zero guidance, no visual identity. Meanwhile we have a beautiful curses TUI with tabs, themes, and an animation system. Configuration belongs inside that world, not in a throwaway CLI experience.

Every config section gets its own animation in the banner zone above the form. Commodore 64 demoscene meets modern terminal art. Section-aware theming: Discord section gets its own visual mood, Telegram gets another, validation success triggers a celebration. The animations are not decoration — they're identity. They communicate "you're in the Discord section" before the user reads a word.

## Creative Brief

This is not a build task with a creative step bolted on. **The creative work IS the first deliverable.** No builder touches code until the visual identity of every config section has been designed, debated, and approved. The animations, visual language, and section theming must be designed collaboratively — with real creative tension between ambition and coherence.

### The bar

Think about what makes great terminal art memorable. The Commodore 64 demoscene didn't have much — 16 colors, 40 columns, 1 MHz — but the constraints bred ingenuity. Scrollers, plasma effects, raster bars, sprite multiplexing. People made those machines sing. That's the energy we want: **terminal art that makes people stop and say "wait, this is a config screen?"**

Each config section should feel like entering a different room. Discord's room has its own atmosphere. Telegram's has another. The validation screen should build tension as checks run and then erupt when everything passes. These aren't loading spinners — they're moments. The user should _want_ to configure things because the experience rewards attention.

We're not going for retro-ironic. We're going for retro-beautiful. The difference matters. Ironic says "look, old-school pixels, how fun." Beautiful says "these constraints produced something genuinely striking." Aim for the latter.

### How the creative team works

**Art Director** — The guardian of coherence. Knows the house style (C64/retro-gaming aesthetic from the existing banner animation system). Evaluates every proposal through one lens: _does this feel like TeleClaude?_ Pushes back on anything generic, anything that could belong to any project. Champions what's distinctive. Has final say on direction.

**Artist** — The explorer. Goes broad and wild within the retro-gaming space. Proposes animation concepts, color palettes, transition effects, idle animations, interaction responses for each config section. Doesn't self-censor — that's the art director's job. Produces concrete visual specs: ASCII art frames, color schemes, animation timing, transition sequences. Shows, doesn't tell.

The dynamic between these roles is the point. The artist pushes boundaries; the art director ensures they serve the whole. Creative tension produces better work than either solo agreement or rigid specs.

### What the creative phase delivers

A visual spec per config section, each defining:

- **Idle animation** — what plays while the user reads, thinks, looks up a credential. Not static. Not distracting. Alive. Think subtle raster effects, gentle color cycling, breathing patterns.
- **Interaction animation** — what happens when the user types, selects, moves between fields. The UI acknowledges the human. Keystrokes might ripple, cursors might trail, selections might pulse.
- **Success celebration** — what happens when a section validates, when all checks pass. This is the payoff. Make it worth the wait. Think confetti in 8-bit, fireworks in 16 colors, a demoscene scroller announcing victory.
- **Error/warning state** — what happens when validation fails. Not punishing — informative and characterful. A glitch effect, a shake, a color shift that says "not quite" without saying "you failed."
- **Color palette / theme** — each section's visual mood. Discord might lean into its indigo/blurple. Telegram into its blue. AI Keys might feel different from messaging adapters. The palette should be distinct per section but harmonious across all.
- **ASCII art assets** — any pixel art, logos, icons, borders, decorative elements specific to a section.

**Creative freedom is the point.** The AIs working on this should brainstorm, propose, critique, and refine — not execute a rigid spec. Surprise us. The best ideas will be ones nobody predicted.

## The Existing Animation Engine

We're not starting from zero. The TUI already has a real animation system. The creative team must understand what exists before designing what comes next.

### What's already built

**Engine** (`teleclaude/cli/tui/animation_engine.py`): Double-buffered rendering with priority-based queuing. Two priority levels — PERIODIC (background) and ACTIVITY (agent events, interrupts periodic). Animations target two zones: big banner (the TELECLAUDE ASCII art) and small logo. The engine runs on a ~100ms tick, respects per-animation speed_ms, and swaps front/back buffers atomically.

**29 animations** across two families:

- **15 general** (`animations/general.py`): FullSpectrumCycle, LetterWave (L/R), LineSweep (top/bottom), MiddleOutVertical, WithinLetterSweep (L/R), RandomPixelSparkle, CheckerboardFlash, WordSplitBlink, DiagonalSweep (DR/DL), LetterShimmer, WavePulse
- **14 agent-specific** (`animations/agent.py`): AgentPulse, AgentWave, AgentHeartbeat, AgentBreathing, AgentSpotlight, AgentLetterCascade, AgentFadeCycle, AgentWordSplit, AgentDiagonalWave, AgentSparkle, AgentMiddleOut, AgentWithinLetterSweep, AgentLineSweep

**Color palettes** (`animation_colors.py`): SpectrumPalette (7-color rainbow), AgentPalette (per-agent: claude/gemini/codex with subtle/muted/normal/highlight tiers), PaletteRegistry for global access.

**Triggers** (`animation_triggers.py`): PeriodicTrigger (random animation every N seconds, filterable by subset), ActivityTrigger (fires on agent events with agent-colored palette).

**Pixel mapping** (`pixel_mapping.py`): Maps the TELECLAUDE banner to (x,y) coordinates. Knows letter boundaries, row/column pixels. This is how animations target specific letters, rows, or diagonals.

### What the engine can't do yet

The current engine is good at what it does — coloring pixels in the banner. But it has limitations that this work must address:

- **Only two targets**: big banner and small logo. Config needs a third target: the config banner zone. The engine needs to become target-agnostic.
- **No state-driven selection**: Animations are random (periodic) or agent-triggered. Config needs state-driven selection: section X in state Y plays animation Z. The trigger system needs a new mode.
- **No section-aware palettes**: Current palettes are spectrum or agent-based. Config needs provider-themed palettes (Discord indigo/blurple, Telegram blue, etc.).
- **No continuous idle animations**: Current periodic animations fire, play, and stop. Config sections need persistent idle animations that run as long as the section is active — subtle, non-distracting, alive.
- **No scroll/motion transitions**: The banner appears and disappears statically. Tab switches, section navigation — these need motion (scroll-out/in, depth transitions).
- **No depth layering**: No concept of z-order. The `tui-animation-art` vision called for animations that render behind the active tab and in front of inactive ones.
- **No animation mode toggle**: No user preference for off / periodic / party. This needs to be a first-class setting.

The creative team should treat the existing engine as a foundation to evolve — not replace. The 29 existing animations and the architecture are proven. Extend, enrich, and where necessary restructure, but don't throw it away.

## Architecture

### What's new

```
telec (TUI)
  +-- Config tab (NEW)
  |     +-- Adapters sub-tab
  |     |     +-- Telegram (form + guidance + animation)
  |     |     +-- Discord (form + guidance + animation)
  |     |     +-- WhatsApp (form + guidance + animation)
  |     |     +-- AI Keys (form + guidance + animation)
  |     +-- People sub-tab (form + guidance + animation)
  |     +-- Notifications sub-tab (form + guidance + animation)
  |     +-- Environment sub-tab (form + guidance + animation)
  |     +-- Validate sub-tab (progress + celebration animation)
  |
  +-- Animation engine evolution (enriches all tabs)
        +-- Target-agnostic rendering (banner, logo, config zone, future zones)
        +-- State-driven animation selection (section + state -> animation)
        +-- Section-aware palettes (provider-themed colors)
        +-- Continuous idle animations
        +-- Scroll/motion transitions between tabs and sections
        +-- Depth layering (z-order for overlapping elements)
        +-- Three-mode toggle: off / periodic / party
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
- The existing animation engine, palettes, pixel mapping — evolved, not replaced

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

The animation system receives context from whatever view is active:

- `target`: which rendering zone (banner, logo, config_banner, future zones)
- `section_id`: which section is active (e.g., "discord", "telegram", "validate", "sessions")
- `state`: idle / interacting / success / error
- `progress`: 0.0-1.0 for validation progress or other progressive states

For config sub-tabs, each provides a banner zone (top N rows). The animation renderer is a callback that the active view calls on each refresh. This contract is consumed by both config-specific animations and the general TUI animation system.

## Phased Execution

### Phase 1: Art Direction (team: art director + artist)

This is the creative heart. The team must:

- **Study the existing engine** — understand what the 29 animations look like, how palettes work, what the banner rendering does today. Build on this, don't ignore it.
- **Design visual concepts per config section** — idle, interaction, success, error animations for each: Telegram, Discord, WhatsApp, AI Keys, People, Notifications, Environment, Validate.
- **Design general TUI animation evolution** — banner scroll-out/in motion, depth-layered effects, tab transition animations. These apply to the whole TUI, not just Config.
- **Define section-aware palettes** — color schemes per provider/section that feel distinct but harmonious.
- **Define the three-mode toggle** — what "off" looks like (static), what "periodic" looks like (current behavior, enhanced), what "party" looks like (all animations active, maximum visual energy).
- **Produce concrete visual specs** — ASCII art frames, color schemes, animation timing, transition sequences. Enough detail that a builder can implement without guessing.
- **Art director approves final direction** — coherent with house style, distinctive to TeleClaude.

### Phase 2: Build — Animation Engine Evolution

- Target-agnostic rendering (decouple from big/small hardcoding)
- State-driven animation selection (new trigger type)
- Section-aware palette registry (provider-themed palettes)
- Continuous idle animation support
- Scroll/motion transition framework
- Depth layering primitives
- Three-mode toggle (off / periodic / party) as user preference
- Integration with existing PeriodicTrigger and ActivityTrigger

### Phase 3: Build — Config Tab Structure

- New Config tab in TUI with sub-tab navigation
- Provider guidance registry (data layer)
- Config component base class / pattern
- Config banner zone wired to animation engine

### Phase 4: Build — Config Components

- Adapter components (Telegram, Discord, WhatsApp, AI Keys) with guidance
- People component
- Notifications component
- Environment component
- Validate component with progress

### Phase 5: Build — Onboard Integration

- `telec onboard` redirects to TUI guided mode
- Sequential traversal through config components
- Skip-completed-sections detection

### Phase 6: Build — Animation Art

- Implement Phase 1 visual specs as Animation subclasses
- Section-specific animations wired to config hookpoints
- Tab transition animations for the whole TUI
- Celebration effects on validation success
- Depth-layered rendering for Sessions and other existing tabs

### Phase 7: Cleanup

- Remove `config_menu.py`
- Remove `onboard_wizard.py`
- Remove or reduce `prompt_utils.py`
- Update `telec config -h` and `telec onboard -h`

## Absorbs

- `config-visual-polish` — fully absorbed (animated config with section theming)
- `tui-animation-art` — fully absorbed (banner motion, depth layering, animation modes, creative-first process). The animation engine evolution and the config visual experience are one unified creative and build effort.

## Dependencies

- None. This todo now owns the full animation evolution. No external dependency needed.
