# TUI Rewrite: Python/curses to TypeScript/Ink

## Goal

Replace the entire Python curses TUI (36 files, 10,344 lines) with a TypeScript/Ink terminal app that lives inside the existing `frontend/` Next.js project. Both web and terminal apps share a common `lib/` layer for state, API, theme, and animation logic.

## Non-Negotiable Requirements

1. **Feature parity**: Every feature in the Python TUI must exist in the Ink TUI. No regressions.
2. **Terminal-only**: This is NOT a browser app. Ink renders React components to the terminal via ANSI escape codes.
3. **No new servers**: The Ink TUI is a CLI client that connects to the existing Python daemon via Unix socket (`/tmp/teleclaude-api.sock`).
4. **Shared library**: ~60-70% of code lives in `lib/` and is consumed by both `app/` (Next.js web) and `cli/` (Ink terminal).
5. **React 18**: Ink 6.x is NOT compatible with React 19. The CLI entry point must use React 18. The web app can continue using React 19.
6. **State-driven**: Unidirectional data flow. User intent -> reducer -> state -> render. No mutable instance variables.
7. **Animation parity + enrichment**: All existing Python animations must be reproduced as pure TypeScript functions, plus new ones.

## Architecture

```
frontend/
  lib/                    # SHARED (web + terminal)
    api/                  # API client, WebSocket, types
    store/                # Zustand store, reducer, selectors
    tree/                 # Hierarchical tree builder + flattener
    animation/            # Pure math animation algorithms + engine
      algorithms/         # Individual animation functions
    theme/                # Color tokens, agent palettes
    keys/                 # Keyboard binding map
    interaction/          # Double-press state machine
    session/              # Session launcher orchestration
    utils/                # Time formatting, path shortening, ANSI stripping
  cli/                    # TERMINAL (Ink)
    index.tsx             # Entry point
    app.tsx               # Root Ink component
    components/           # Ink UI components
      sessions/           # Session tree view + node components
      preparation/        # Todo tree view + node components
      configuration/      # Settings tabs
      modals/             # Start session, confirm, inputs
      animation/          # Terminal animation renderer (drawille + chalk)
      layout/             # Banner, TabBar, Footer, Notification
    hooks/                # Terminal-specific React hooks
    lib/                  # Terminal utilities
      tmux.ts             # Tmux pane manager
      persistence.ts      # State file I/O
  app/                    # WEB (Next.js) - existing, enhanced
    components/
      animation/          # Web animation renderer (canvas)
```

## Technology Stack

### CLI Dependencies (new)

- `ink@^6.7.0` - React terminal renderer
- `react@^18.3.1` - React 18 (NOT 19 - Ink incompatibility)
- `zustand@^5` - State management with external access
- `immer@^10` - Immutable state updates in reducer
- `ws@^8` - WebSocket client for Node.js
- `chalk@^5` - Terminal colors
- `drawille@^2` - Braille-character pixel rendering (2x4 sub-pixel resolution)
- `fullscreen-ink@^1` - Alternate screen buffer for fullscreen mode
- `ink-big-text@^2` - FIGlet ASCII art banner
- `ink-gradient@^3` - Gradient text rendering
- `cli-spinners@^3` - Spinner frame sets

### Dev Dependencies (new)

- `vitest@^2` - Unit testing
- `@ink-testing-library/react@^1` - Component testing (mirrors React Testing Library)
- `@types/ws@^8`

## State Management

Port the existing Python reducer (`state.py`) to Zustand:

### Store Shape

```typescript
interface TuiStore {
  // View states (from Python TuiState)
  sessions: SessionViewState;
  preparation: PreparationViewState;
  config: ConfigViewState;

  // Global
  activeTab: 'sessions' | 'preparation' | 'configuration';
  animationMode: 'off' | 'periodic' | 'party';
  connected: boolean;

  // Data (from WebSocket)
  sessionList: SessionInfo[];
  computerList: ComputerInfo[];
  projectList: ProjectInfo[];

  // Actions
  dispatch: (intent: Intent) => void;
}
```

### Intent Types (all 25 from Python)

```
SYNC_SESSIONS, SET_SELECTION, SET_PREVIEW, TOGGLE_STICKY,
TOGGLE_COLLAPSE, SET_TAB, AGENT_ACTIVITY, CLEAR_HIGHLIGHTS,
SET_CONFIG_GUIDED_MODE, SET_CONFIG_SUBTAB, SET_COMPUTER,
TOGGLE_ANIMATION, SYNC_TODOS, TOGGLE_TODO_EXPAND,
SET_SORT_ORDER, SET_INPUT_HIGHLIGHT, SET_OUTPUT_HIGHLIGHT,
CLEAR_TEMP_HIGHLIGHT, SET_LAST_OUTPUT_SUMMARY,
SET_SCROLL_POSITION, TOGGLE_SESSION_COLLAPSE,
SET_PANE_SESSION, CLEAR_PANE_SESSION, SET_FOCUS_SOURCE,
REFRESH_COMPLETE
```

## WebSocket Events

The Ink TUI subscribes to the daemon's WebSocket and handles:

- `sessions_initial` - Full session list on connect
- `projects_initial` - Full project list on connect
- `session_started` - New session created
- `session_updated` - Session state change
- `session_closed` - Session terminated
- `agent_activity` - Tool use, streaming, thinking events
- `refresh` - Full data refresh
- `error` - Error notification

## Tmux Integration

The Ink TUI manages tmux panes for session viewing:

- Declarative grid layouts: 1x1, 1x2, 2x2, 2x3 (max 5 sticky + 1 preview)
- Layout signature caching (only rebuild if structure changed)
- Agent-specific background colors per pane
- Remote SSH session support with env forwarding
- Pane focus reverse sync (poll active pane, highlight in tree)
- Direct `child_process.execSync` for tmux commands

## Keyboard System

Shared key binding map consumed by both Ink (`useInput`) and web (`onKeyDown`):

### Global Keys

- `q` - Quit
- `1/2/3` - Switch tabs (Sessions/Preparation/Configuration)
- `r` - Refresh data
- `a` - Toggle animation mode

### Sessions View Keys

- `Up/Down/j/k` - Navigate tree
- `Space` (single) - Preview session in pane
- `Space` (double-press <650ms) - Toggle sticky
- `Enter` - Focus session pane
- `n` - New session modal
- `x` - End session
- `c` - Collapse/expand session detail

### Preparation View Keys

- `Up/Down` - Navigate todo tree
- `Space` - Expand/collapse todo
- `Enter` - Open todo in editor

## Animation System

### Architecture

- Pure functions: `(frame: number, config: AnimationConfig, target: AnimationTarget) => ColorGrid`
- Double-buffered engine with priority system (PERIODIC < ACTIVITY < MANUAL)
- 3 trigger types: Periodic (timer), Activity (agent events), StateDriven (section state)
- Terminal renderer: drawille braille characters + chalk colors
- Web renderer: HTML canvas with pixel-sized squares

### Existing Animations to Reproduce (from Python)

**General (15):** FullSpectrumCycle, LetterWaveLR, LetterWaveRL, LineSweepTopBottom, LineSweepBottomTop, MiddleOutVertical, WithinLetterSweepLR, WithinLetterSweepRL, RandomPixelSparkle, CheckerboardFlash, WordSplitBlink, DiagonalSweepDR, DiagonalSweepDL, LetterShimmer, WavePulse

**Agent-specific (14):** AgentPulse, AgentWaveLR, AgentWaveRL, AgentLineSweep, AgentMiddleOut, AgentSparkle, AgentWithinLetterSweep, AgentHeartbeat, AgentWordSplit, AgentLetterCascade, AgentFadeCycle, AgentSpotlight, AgentBreathing, AgentDiagonalWave

**Config section (4):** PulseAnimation, TypingAnimation, SuccessAnimation, ErrorAnimation

### New Animations to Add

matrixRain, rainbowWave, starfield, fire, plasma, gameOfLife, spiral, perlinNoise, ripple, lightning

### Theme Tokens

Agent color palettes with dark/light mode support:

- Claude: orange spectrum (#875f00 -> #d7af87 -> #ffffff)
- Gemini: purple spectrum (#8787af -> #af87ff -> #ffffff)
- Codex: teal spectrum (#5f8787 -> #87afaf -> #ffffff)

General palettes: Spectrum, Fire, Ocean, Forest, Sunset

## Persistence

State persisted to `~/.teleclaude/tui_state.json`:

- Sticky sessions (max 5)
- Collapsed sessions
- Input/output highlights
- Last output summaries
- Expanded todos
- Preview session
- Animation mode

Atomic write with temp file + rename. Advisory locking via `fs.flock`.

## Testing Strategy

- **Unit**: Reducer (all 25 intents), tree builder, animation algorithms, double-press logic, layout system
- **Component**: Ink Testing Library for all views and nodes
- **Integration**: Mock Unix socket server, WebSocket event flow
- **Visual**: Screenshot comparison for animations (terminal + web)
