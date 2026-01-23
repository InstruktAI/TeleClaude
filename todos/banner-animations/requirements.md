# Banner Animation System Requirements

## Overview

Implement a comprehensive animation system for both the large ASCII banner (6 lines) and small ASCII logo (3 lines) that displays "TELECLAUDE" in the TUI. The system should support two animation trigger modes: periodic random animations using full color spectrum, and agent-activity-triggered animations using agent-specific color palettes.

## Goals

1. **Visual Interest**: Add dynamic color animations to both banners to make the TUI more engaging
2. **Activity Indication**: Use agent-specific color animations to visually communicate agent activity
3. **Aesthetic Quality**: Create smooth, professional-looking animations using the character-as-pixel model
4. **Performance**: Ensure animations don't impact TUI responsiveness or daemon performance

## Animation Specifications

See [animation-matrix.md](./animation-matrix.md) for complete animation catalog.

### Animation Categories

**General Animations (15 total)**

- Triggered periodically (every 60 seconds)
- Use full rainbow/spectrum color palette
- Select 1 random animation per trigger
- Duration: 3-8 seconds
- Can be interrupted by agent activity

**Agent-Specific Animations (14 total)**

- Triggered on WebSocket session activity
- Use agent color palette (Muted, Normal, Highlight)
- Select 1 random animation per trigger
- Duration: 2-5 seconds
- Restart on each activity pulse

### Physical Constraints

**Big ASCII Banner**

- Grid: ~80-90 characters wide × 5 lines tall
- Letter size: ~8-9 characters wide per letter
- Supports: Full directional sweeps, within-letter animations, middle-out vertical

**Small ASCII Logo**

- Grid: 39 characters wide × 3 lines tall
- Letter size: Variable, ~4 characters wide per letter
- Supports: Color changes only, letter-level waves, line sweeps

### Character-as-Pixel Model

Each ASCII character is treated as a single pixel:

- One color per character at any given time
- No sub-character gradients or effects
- Animations change which color each character has over time

## Functional Requirements

### FR-1: Animation Engine

- **FR-1.1**: Create animation engine that manages frame updates at configurable FPS
- **FR-1.2**: Support both big banner and small logo simultaneously
- **FR-1.3**: Implement double-buffering to prevent flicker
- **FR-1.4**: Allow animation interruption and queuing

### FR-2: Color Management

- **FR-2.1**: Define full spectrum color palette (rainbow)
- **FR-2.2**: Use existing agent color palettes from theme.py (Muted, Normal, Highlight)
- **FR-2.3**: Allow each animation to select subset of available colors
- **FR-2.4**: Support color transitions with easing functions

### FR-3: Trigger System

- **FR-3.1**: Implement 60-second periodic timer for general animations
- **FR-3.2**: Listen to WebSocket session activity events
- **FR-3.3**: Detect agent type (Claude, Gemini, Codex) from activity
- **FR-3.4**: Queue animations appropriately based on trigger priority

### FR-4: Animation Implementations

- **FR-4.1**: Implement all 15 general animations from matrix
- **FR-4.2**: Implement all 14 agent-specific animations from matrix
- **FR-4.3**: Each animation should be modular and self-contained
- **FR-4.4**: Support configurable duration, speed, and easing per animation

### FR-5: Banner Integration

- **FR-5.1**: Integrate with existing banner rendering in `widgets/banner.py`
- **FR-5.2**: Integrate with small logo rendering in `app.py:_render_hidden_banner_header()`
- **FR-5.3**: Preserve existing non-animated rendering as fallback
- **FR-5.4**: Support disabling animations via configuration

## Non-Functional Requirements

### NFR-1: Performance

- Animation frame updates must not block TUI event loop
- Target: < 5ms per frame update
- Batch curses color updates to minimize syscalls

### NFR-2: Resource Usage

- Minimal CPU usage when animations not active
- No memory leaks from animation state
- Clean shutdown of animation threads/tasks

### NFR-3: Configuration

- Allow user to disable animations entirely
- Allow user to adjust animation frequency
- Allow user to select specific animation subsets

### NFR-4: Maintainability

- Clear separation between animation logic and rendering
- Easy to add new animations
- Comprehensive unit tests for animation calculations

## Technical Architecture

### Components

1. **AnimationEngine** (`teleclaude/cli/tui/animation_engine.py`)
   - Manages animation lifecycle
   - Handles frame timing and updates
   - Coordinates with banner widgets

2. **Animation Definitions** (`teleclaude/cli/tui/animations/`)
   - Base animation class
   - Individual animation implementations (G1-G15, A1-A14)
   - Color palette utilities

3. **Banner Integration** (modifications to existing files)
   - `widgets/banner.py`: Add animation support to big banner
   - `app.py`: Add animation support to small logo
   - `app.py`: Wire up trigger events

4. **Activity Monitor** (`teleclaude/cli/tui/activity_monitor.py`)
   - Listen to WebSocket events
   - Detect agent type
   - Trigger agent-specific animations

### Data Flow

```
WebSocket Activity → Activity Monitor → AnimationEngine → Banner Widget → Curses Display
     ↓
Periodic Timer → AnimationEngine → Logo Rendering → Curses Display
```

## Acceptance Criteria

1. ✅ All 29 animations (15 general + 14 agent) are implemented and functional
2. ✅ Periodic animations trigger every 60 seconds with random selection
3. ✅ Agent activity triggers correct agent-colored animations
4. ✅ Both big banner and small logo animate appropriately
5. ✅ Animations run smoothly without TUI lag or flicker
6. ✅ Animations can be interrupted by higher-priority triggers
7. ✅ Configuration option to disable animations exists
8. ✅ Unit tests cover animation logic and timing
9. ✅ No performance degradation in TUI responsiveness
10. ✅ Clean daemon shutdown with no animation thread hangs

## Out of Scope

- Sub-character pixel-level animations
- 3D effects or perspective transformations
- Audio synchronization
- Animation customization beyond configuration toggles
- Frame-perfect synchronization across multiple terminals

## Dependencies

- Existing theme system (`teleclaude/cli/tui/theme.py`)
- Curses color pair management
- WebSocket event system
- TUI main loop and rendering pipeline

## References

- [animation-matrix.md](./animation-matrix.md) - Complete animation catalog
- `teleclaude/cli/tui/theme.py` - Existing color definitions
- `teleclaude/cli/tui/widgets/banner.py` - Big banner rendering
- `teleclaude/cli/tui/app.py` - Small logo rendering and main loop
