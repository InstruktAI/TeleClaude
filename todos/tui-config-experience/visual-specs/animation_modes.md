# Three-Mode Animation Toggle — Behavior Spec

## Modes

### OFF

- `animation_engine.is_enabled = False`
- Banner renders in static muted color (default banner_attr from theme.py)
- No color overlays on any element
- No scene animations
- Tab transitions are instant (no animation)
- Cleanest, most professional appearance
- Use case: presentations, screen sharing, accessibility preference

### PERIODIC (default)

- Current behavior preserved for Sessions and Preparation tabs
- PeriodicTrigger: fires every 60s with random general animation (3-8s)
- ActivityTrigger: fires on agent activity with agent-colored animation
- Config tab additions:
  - Section-aware idle animations play continuously (via StateDrivenTrigger)
  - Interaction/success/error animations fire on user actions
- Tab transitions: Cross-Fade (0.3s)
- Banner scene rotation: Starfield, ShootingStar
- Scene animations (character): DISABLED (too distracting for default)
- Mood: alive but focused

### PARTY

- Everything amplified
- PeriodicTrigger interval: 10s (was 60s)
- Config tab: same section-aware animations, but success celebrations are
  multi-stage (ValidateSuccess fireworks at full intensity)
- Tab transitions: Cross-Fade (0.3s)
- Scene animations (character) ENABLED:
  - Bicycle rider: random interval 3-5 minutes
  - Pixel cat: random interval 4-6 minutes
  - Demoscene scroller: random interval 5-8 minutes
  - (at most one scene at a time)
- Banner scene rotation: All Category A + PlasmaWave, RasterBars, MarqueeWrap
- Mood: C64 demo — showing off, having fun

## Toggle

### Keybinding

- TBD (Ctrl+A conflicts with tmux prefix — needs alternative keybinding)
- Cycles: OFF → PERIODIC → PARTY → OFF
- Visual feedback: banner briefly flashes to acknowledge mode change

### Status Indicator

Shown in TUI status/footer bar:

- OFF: `[◻]` (empty square)
- PERIODIC: `[◈]` (diamond)
- PARTY: `[★]` (star)

### Persistence

- Stored in `~/.teleclaude/tui_state.json` as `"animation_mode": "off"|"periodic"|"party"`
- Loaded on TUI startup
- Default: `"periodic"` if no setting exists

## Automatic Mode Behavior

### Validation Success

When config validation passes:

1. Temporarily switch to PARTY for 10 seconds
2. Play ValidateSuccess (fireworks)
3. After 10s, restore previous mode
4. This happens regardless of current mode (even OFF gets the celebration)

### Guided Onboarding

When entering guided mode (telec onboard):

- Force PERIODIC mode for the duration of onboarding
- Restore previous mode on exit
- Ensures a friendly, alive experience without overwhelming new users
