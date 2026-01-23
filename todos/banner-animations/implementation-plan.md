# Banner Animation System - Implementation Plan

## Overview

Implement a lightweight, custom animation engine for TELECLAUDE banner color animations. The engine manages frame timing, animation state, and color palette selection without external animation libraries. Integration with existing curses rendering through color overrides.

## Architecture

### Components

```
animation_engine.py
├── AnimationEngine         # Main coordinator
│   ├── update(frame)       # Updates current animation
│   ├── play(animation, palette)  # Start animation
│   └── get_colors()        # Returns pixel color grid
│
animation_colors.py
├── ColorPalette            # Abstract base
├── SpectrumPalette         # Rainbow/full spectrum
├── AgentPalette            # Muted/Normal/Highlight trio
└── palette_registry        # Palette instances
│
animations/
├── base.py
│   └── Animation           # Base class (abstract)
│       ├── update(frame)   # Returns {(x,y): color_idx}
│       └── duration_frames # How long animation runs
│
├── general.py              # G1-G15 animations
└── agent.py                # A1-A14 animations
│
animation_triggers.py
├── PeriodicTrigger         # 60s timer
└── ActivityTrigger         # WebSocket listener
│
pixel_mapping.py
├── BannerPixels            # Coordinates for big banner
└── LogoPixels              # Coordinates for small logo
```

### Data Structures

**Pixel Grid:**

```python
# animation_engine.colors: dict[(x, y)] = color_index
# x: 0 to banner_width
# y: 0 to banner_height
# color_index: 0-N (index into current palette)
```

**Animation Return Format:**

```python
def update(frame: int) -> dict[tuple[int, int], int]:
    """
    Args:
        frame: Frame number (0 to duration_frames-1)

    Returns:
        {(x, y): color_index, ...}
        Only changed pixels included (sparse dict)
    """
```

**Palette Format:**

```python
class ColorPalette:
    colors: list[int]  # Curses color pair indices
    name: str

    def get(self, index: int) -> int:
        """Get color pair for palette index (wraps if needed)"""
```

## Implementation Sequence

### Phase 1: Foundation (Day 1)

**1.1 Pixel Mapping** (`pixel_mapping.py`)

- Define `BannerPixels`: Map of (x, y) → character position in big banner
- Define `LogoPixels`: Map of (x, y) → character position in small logo
- Account for actual banner rendering positions (rows 0-5 for big, rows 0-2 for logo)
- Add utility functions: `get_letter_pixels(letter_num)`, `get_row_pixels(row_num)`, etc.

**1.2 Color Management** (`animation_colors.py`)

- `ColorPalette` abstract base class
- `SpectrumPalette`: Construct rainbow from curses colors (red, yellow, green, cyan, blue, magenta)
- `AgentPalette`: Use existing theme.py agent colors (Muted, Normal, Highlight)
- `palette_registry`: Store instances of all palettes
- Helper: `create_agent_palette(agent_name)` → AgentPalette

**1.3 Animation Base Class** (`animations/base.py`)

```python
class Animation:
    def __init__(self, palette: ColorPalette, duration_seconds: float, speed_ms: int = 100):
        self.palette = palette
        self.duration_frames = int(duration_seconds * 1000 / speed_ms)
        self.speed_ms = speed_ms

    def update(self, frame: int) -> dict[tuple[int, int], int]:
        """Return {(x,y): color_index} for this frame"""
        raise NotImplementedError

    def is_complete(self, frame: int) -> bool:
        return frame >= self.duration_frames
```

### Phase 2: Simple Animations (Day 2-3)

**2.1 Implement G1: Full Spectrum Cycle** (`animations/general.py`)

- All pixels cycle through entire palette synchronously
- Pattern: pixel color = palette[frame % len(palette)]

**2.2 Implement G2: Letter Wave (L→R)**

- Letters light up sequentially left to right
- Pattern: For each letter, determine if it's "on" this frame
- Stagger: letter_index = frame % num_letters

**2.3 Implement G3: Letter Wave (R→L)**

- Mirror of G2, reversed direction

**2.4 Implement A1: Agent Pulse**

- All pixels pulse through 3 agent colors
- Pattern: frame % 3 determines which of 3 colors

**2.5 Implement A2: Agent Wave (L→R)**

- Agent-specific version of letter wave

### Phase 3: Core Engine (Day 3-4)

**3.1 Animation Engine** (`animation_engine.py`)

```python
class AnimationEngine:
    def __init__(self):
        self.current_animation: Animation | None = None
        self.frame_count: int = 0
        self.colors: dict[tuple[int, int], int] = {}

    def play(self, animation: Animation) -> None:
        """Start new animation, interrupting current"""
        self.current_animation = animation
        self.frame_count = 0

    def update(self) -> None:
        """Call once per TUI render cycle (every ~100ms)"""
        if not self.current_animation:
            return

        new_colors = self.current_animation.update(self.frame_count)
        self.colors.update(new_colors)

        if self.current_animation.is_complete(self.frame_count):
            self.current_animation = None

        self.frame_count += 1

    def get_color(self, x: int, y: int) -> int | None:
        """Get color for pixel, or None if no animation"""
        return self.colors.get((x, y))
```

**3.2 Trigger System** (`animation_triggers.py`)

```python
class PeriodicTrigger:
    def __init__(self, engine: AnimationEngine, interval_sec: int = 60):
        self.engine = engine
        self.task: asyncio.Task | None = None

    async def start(self):
        """Run infinite periodic trigger loop"""
        while True:
            await asyncio.sleep(self.interval_sec)
            animation = self._select_random_general_animation()
            palette = palette_registry.get('spectrum')
            self.engine.play(animation)

class ActivityTrigger:
    def __init__(self, engine: AnimationEngine):
        self.engine = engine

    def on_agent_activity(self, agent_name: str):
        """Called from WebSocket event handler"""
        animation = self._select_random_agent_animation()
        palette = palette_registry.get(f'agent_{agent_name}')
        self.engine.play(animation)
```

### Phase 4: Rendering Integration (Day 4-5)

**4.1 Big Banner Integration** (`widgets/banner.py`)

- Modify `render_banner(stdscr, start_row, width, animation_engine)` signature
- For each character in banner:
  ```python
  color = animation_engine.get_color(x, y)
  if color is not None:
      attr = curses.color_pair(color)
  else:
      attr = banner_attr  # Default
  stdscr.addstr(row, col, char, attr)
  ```

**4.2 Small Logo Integration** (`app.py:_render_hidden_banner_header()`)

- Similar approach for small logo
- Pass animation_engine to function
- Apply colors to logo characters

**4.3 App Integration** (`app.py:_render()`)

- Call `animation_engine.update()` at start of render cycle
- Pass engine to banner/logo rendering functions
- Initialize triggers on first render

### Phase 5: Remaining Animations (Day 5-7)

**5.1 Implement Medium Complexity** (G4-G8, A5-A9)

- Within-letter sweeps: Iterate through letter pixels by column/row
- Line sweeps: Track which row is active
- Middle-out: Track distance from center row

**5.2 Implement High Complexity** (G10-G15, A10-A14)

- Random pixel sparkle: Use `random.choice(all_pixels)` per frame
- Diagonal sweeps: Map (x,y) to diagonal coordinate
- Spotlight: Calculate window position, apply distance-based fade

### Phase 6: Testing & Polish (Day 7-8)

**6.1 Unit Tests** (`tests/unit/test_animations.py`)

- Test each animation produces expected frame outputs
- Test pixel mapping correctness
- Test color palette cycling
- Test animation completion detection

**6.2 Integration Tests** (`tests/integration/test_animation_engine.py`)

- Test engine update loop
- Test animation interruption
- Test trigger firing
- Test rendering integration

**6.3 Manual Testing**

- Run TUI with animations enabled
- Verify visual quality and smoothness
- Check for color flicker or artifacts
- Monitor performance/CPU usage

**6.4 Configuration** (`config.yml`)

- Add `ui.animations.enabled: true/false`
- Add `ui.animations.periodic_interval_sec: 60`
- Add `ui.animations.disabled_pools: []` (exclude animation types if needed)

## Integration Points

### 1. Main Render Loop (`app.py:_render()`)

```python
def _render(self, stdscr, height, width):
    # ... existing code ...

    # Update animations
    self.animation_engine.update()

    # Pass engine to renderers
    render_banner(stdscr, 0, width, self.animation_engine)
    self.tab_bar.render(stdscr, tab_row, width, logo_width)
    self._render_hidden_banner_header(stdscr, width, self.animation_engine)
```

### 2. Banner Rendering (`widgets/banner.py`)

```python
def render_banner(stdscr, start_row, width, animation_engine=None):
    for i, line in enumerate(BANNER_LINES):
        for j, ch in enumerate(line):
            color_idx = None
            if animation_engine:
                color_idx = animation_engine.get_color(j, i)

            attr = curses.color_pair(color_idx) if color_idx else banner_attr
            stdscr.addstr(start_row + i, j, ch, attr)
```

### 3. WebSocket Activity Handler

```python
# In session update handler
def on_session_activity(agent_name: str):
    if animation_engine and config.animations.enabled:
        activity_trigger.on_agent_activity(agent_name)
```

### 4. Daemon Startup (`__main__.py` or `daemon.py`)

```python
# Initialize animation system
animation_engine = AnimationEngine()
periodic_trigger = PeriodicTrigger(animation_engine)
activity_trigger = ActivityTrigger(animation_engine)

# Start periodic trigger (if enabled)
if config.animations.enabled:
    asyncio.create_task(periodic_trigger.start())
```

## File Checklist

- [ ] `teleclaude/cli/tui/pixel_mapping.py` - Pixel coordinate definitions
- [ ] `teleclaude/cli/tui/animation_colors.py` - Palette management
- [ ] `teleclaude/cli/tui/animations/base.py` - Base Animation class
- [ ] `teleclaude/cli/tui/animations/general.py` - G1-G15 implementations
- [ ] `teleclaude/cli/tui/animations/agent.py` - A1-A14 implementations
- [ ] `teleclaude/cli/tui/animation_engine.py` - Core engine
- [ ] `teleclaude/cli/tui/animation_triggers.py` - Periodic + activity triggers
- [ ] `tests/unit/test_animations.py` - Animation unit tests
- [ ] `tests/integration/test_animation_engine.py` - Integration tests
- [ ] Modifications to `widgets/banner.py` - Big banner integration
- [ ] Modifications to `app.py` - Small logo integration
- [ ] Configuration updates in `config.sample.yml`

## Performance Targets

- Animation update: < 5ms
- Curses rendering: No additional overhead (batch color updates)
- CPU usage: < 1% when animating
- Memory: < 1MB for engine + animations

## Rollback Plan

If issues arise:

1. Set `config.animations.enabled: false` in config
2. Animations disabled, TUI renders normally
3. No curses code changes needed - fallback to default attrs

## Success Criteria

1. All 29 animations implemented and tested
2. Periodic trigger fires every 60 seconds
3. Agent activity triggers animations with correct colors
4. Both big banner and small logo animate smoothly
5. No TUI lag or visual artifacts
6. Configuration option to disable animations
7. Unit and integration tests pass
8. Performance targets met
