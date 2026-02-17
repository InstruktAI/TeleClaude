# Implementation Plan: TUI Rewrite

## Work Items Overview

13 parallel streams organized into 4 phases. Each item has clear inputs, outputs, acceptance criteria, and dependency markers. Items within the same phase can be built in parallel by separate agents.

---

## Phase 1: Foundation (Shared Library)

All items in Phase 1 are independent and can be built in parallel by 7 agents.

---

### WI-01: API Types & Client

**Stream**: A (API Layer)
**Size**: Large
**Files to create**:

- `lib/api/types.ts` - All TypeScript types generated from Python Pydantic models
- `lib/api/client.ts` - HTTP client over Unix socket
- `lib/api/websocket.ts` - WebSocket manager with auto-reconnect

**Inputs**:

- Python `teleclaude/api_models.py` (Pydantic models)
- Python `teleclaude/cli/api_client.py` (HTTP + WebSocket logic)
- Existing `frontend/lib/proxy/daemon-client.ts` (reuse Unix socket pattern)

**Outputs**:

- `TelecAPIClient` class with typed methods for all daemon endpoints
- `WebSocketManager` class with subscribe/unsubscribe per computer
- Complete TypeScript type definitions matching Python DTOs

**Acceptance Criteria**:

- [ ] All Python DTO types have TypeScript equivalents
- [ ] HTTP client connects to Unix socket at `/tmp/teleclaude-api.sock`
- [ ] WebSocket auto-reconnects with exponential backoff (1s -> 30s)
- [ ] Subscribe/unsubscribe per computer works
- [ ] Unit tests for client methods with mocked responses

**Key Details**:

- Reuse `daemonRequest` pattern from existing `daemon-client.ts`
- WebSocket: use `ws` library with `socketPath` option
- Backoff: 1s initial, 2x multiplier, 30s max, jitter
- Events: parse JSON, validate type field, dispatch to callback
- API endpoints: `/sessions`, `/computers`, `/projects`, `/settings`, `/agent-availability`, `/todos`

**Dependencies**: None

---

### WI-02: State Store & Reducer

**Stream**: B (State Layer)
**Size**: Large
**Files to create**:

- `lib/store/types.ts` - State shape, Intent types, view state interfaces
- `lib/store/reducer.ts` - Pure reducer function (port all 25 intents from Python)
- `lib/store/index.ts` - Zustand store with Immer + persist middleware
- `lib/store/selectors.ts` - Derived state selectors (sticky IDs, highlighted sessions, etc.)

**Inputs**:

- Python `teleclaude/cli/tui/state.py` (TuiState, reduce_state, all Intent types)
- Python `teleclaude/cli/tui/types.py` (StickySessionInfo, TodoStatus, etc.)

**Outputs**:

- Zustand store with external access (no React Context required)
- `dispatch(intent)` function matching Python's `reduce_state`
- Persistence middleware for `~/.teleclaude/tui_state.json`

**Acceptance Criteria**:

- [ ] All 25 intent types ported with identical behavior
- [ ] Zustand store accessible outside React (for WebSocket handlers)
- [ ] Immer middleware for immutable updates
- [ ] Persist middleware saves/loads from state file
- [ ] Unit tests for every intent type (pure reducer tests)

**Key Details**:

- Port `reduce_state` line-by-line from Python `state.py:83-472`
- SessionViewState: sticky_sessions (max 5), preview, collapsed, highlights, selected_index, scroll_offset
- PreparationViewState: expanded_todos set, selected_index
- ConfigViewState: active_subtab, guided_mode, selected_computer
- SYNC_SESSIONS must prune stale sticky/preview references
- AGENT_ACTIVITY sets input_highlight, clears output_highlight, updates last_output_summary

**Dependencies**: None

---

### WI-03: Tree Builder

**Stream**: C (Tree Layer)
**Size**: Medium
**Files to create**:

- `lib/tree/types.ts` - TreeNode union type (Computer | Project | Session | Todo | File)
- `lib/tree/builder.ts` - Build hierarchical tree from flat session/project/computer lists
- `lib/tree/flatten.ts` - Flatten tree to scrollable list with depth/indent info

**Inputs**:

- Python `teleclaude/cli/tui/views/sessions.py:_build_tree()` (tree construction logic)
- Python `teleclaude/cli/tui/views/preparation.py` (todo tree logic)

**Outputs**:

- `buildSessionTree(computers, projects, sessions)` - hierarchical tree
- `buildPrepTree(projects)` - todo tree
- `flattenTree(tree, collapsed)` - flat list for scrolling/rendering

**Acceptance Criteria**:

- [ ] Session tree: Computer -> Project -> Session hierarchy
- [ ] Prep tree: Project -> Todo -> File hierarchy
- [ ] Flatten respects collapsed state (skips children of collapsed nodes)
- [ ] Each flat item carries depth, parent refs, node type
- [ ] Unit tests for tree building and flattening

**Key Details**:

- Tree sorts: computers alphabetical, projects alphabetical, sessions by start_time desc
- Sticky sessions appear at top of their computer/project group
- Collapsed nodes still count in flat list (just skip children)
- Handle orphan sessions (computer/project not in list)

**Dependencies**: None

---

### WI-04: Interaction State Machine

**Stream**: D (Interaction)
**Size**: Small
**Files to create**:

- `lib/interaction/gesture.ts` - Double-press detection, guard period

**Inputs**:

- Python `teleclaude/cli/tui/views/interaction.py` (TreeInteractionState)

**Outputs**:

- `TreeInteractionState` class with `decidePreviewAction(itemId)` method
- Returns: `'preview'` (single press), `'toggle'` (double press), `'none'` (guard period)

**Acceptance Criteria**:

- [ ] Single press (<650ms since last) returns 'preview'
- [ ] Double press (within 650ms) returns 'toggle'
- [ ] Triple press (guard period) returns 'none'
- [ ] Different item ID resets state
- [ ] Unit tests with mocked timers

**Key Details**:

- Port from Python `interaction.py:28-90`
- 650ms threshold (DOUBLE_PRESS_THRESHOLD)
- Guard state prevents unintended triple-press toggle
- State machine: IDLE -> FIRST_PRESS -> (timeout -> IDLE | press -> DOUBLE_PRESS -> GUARD -> IDLE)

**Dependencies**: None

---

### WI-05: Theme & Colors

**Stream**: E (Theme)
**Size**: Medium
**Files to create**:

- `lib/theme/tokens.ts` - Agent color palettes, animation palettes, dark/light mode
- `lib/theme/ink-colors.ts` - Chalk color mappers for terminal
- `lib/theme/css-variables.ts` - CSS custom properties for web

**Inputs**:

- Python `teleclaude/cli/tui/theme.py` (color pairs, palettes)
- Python `teleclaude/cli/tui/animation_colors.py` (animation palettes)

**Outputs**:

- `THEME_TOKENS` object with agent colors x dark/light
- `getAgentChalk(agent, level)` for terminal
- `generateCSSVariables(isDark)` for web

**Acceptance Criteria**:

- [ ] All agent colors (claude/gemini/codex) with 4 levels (subtle/muted/normal/highlight)
- [ ] Dark and light mode variants
- [ ] Animation palettes: Spectrum, Fire, Ocean, Forest, Sunset
- [ ] Terminal: chalk hex color functions
- [ ] Web: CSS custom properties generation
- [ ] `detectDarkMode()` works in both terminal (env var) and browser (media query)

**Key Details**:

- Python theme.py has 8 separate color pair dicts with hardcoded IDs 1-69
- Simplify to semantic token system: agent x mode x level -> hex color
- Agent palettes for animations: 3-color arrays [muted, normal, highlight]
- `APPEARANCE_MODE` env var for terminal dark/light detection

**Dependencies**: None

---

### WI-06: Keyboard Bindings

**Stream**: F (Keys)
**Size**: Medium
**Files to create**:

- `lib/keys/bindings.ts` - Complete key binding map (global + per-view)
- `lib/keys/types.ts` - KeyBinding interface, KeyContext type

**Inputs**:

- Python `teleclaude/cli/tui/views/sessions.py` (key handlers in handle_key)
- Python `teleclaude/cli/tui/views/preparation.py` (key handlers)
- Python `teleclaude/cli/tui/app.py` (global key handlers)

**Outputs**:

- `globalBindings` array (q, 1/2/3, r, a)
- `sessionsBindings` array (arrows, space, enter, n, x, c, etc.)
- `preparationBindings` array
- `configBindings` array

**Acceptance Criteria**:

- [ ] All keys from Python TUI are mapped
- [ ] Each binding has key, description, handler callback
- [ ] Global bindings work in all views
- [ ] View-specific bindings only active when view is focused
- [ ] Bindings are data-driven (can be displayed in help/footer)

**Key Details**:

- Python uses curses key constants; map to Ink's `useInput` key names
- Special keys: KEY_UP -> 'upArrow', KEY_DOWN -> 'downArrow', etc.
- Space key needs special handling (double-press detection)
- Ctrl+C is handled by Ink automatically (exit)

**Dependencies**: None

---

### WI-07: Utilities

**Stream**: G (Utils)
**Size**: Small
**Files to create**:

- `lib/utils/time.ts` - Relative time formatting ("2m ago", "1h ago")
- `lib/utils/path.ts` - Path shortening for display (~/... truncation)
- `lib/utils/ansi.ts` - ANSI escape code stripping

**Inputs**:

- Python `teleclaude/cli/tui/views/sessions.py` (time formatting in render)
- Python `teleclaude/cli/ansi.py` (ANSI stripping)

**Outputs**:

- `formatRelativeTime(date)` - "2m ago", "1h ago", "3d ago"
- `shortenPath(path, maxLen)` - "~/Workspace/.../project"
- `stripAnsi(text)` - Remove ANSI escape codes

**Acceptance Criteria**:

- [ ] Time: seconds/minutes/hours/days/weeks formatting
- [ ] Path: Home dir -> ~, middle truncation with ...
- [ ] ANSI: Strips all SGR, cursor, and OSC sequences
- [ ] Unit tests for edge cases

**Dependencies**: None

---

## Phase 2: Animation System

Can be built in parallel with Phase 1. Independent of other phases.

---

### WI-08: Animation Core

**Stream**: N (Animation)
**Size**: Large
**Files to create**:

- `lib/animation/types.ts` - AnimationAlgorithm, ColorGrid, AnimationConfig, AnimationTarget, AnimationPriority
- `lib/animation/palettes.ts` - All color palettes as hex string arrays
- `lib/animation/pixel-map.ts` - Banner/logo pixel coordinates, letter boundaries
- `lib/animation/engine.ts` - Double-buffered animation engine with priority queue
- `lib/animation/triggers.ts` - PeriodicTrigger, ActivityTrigger, StateDrivenTrigger

**Inputs**:

- Python `teleclaude/cli/tui/animation_engine.py` (AnimationSlot, priority system)
- Python `teleclaude/cli/tui/pixel_mapping.py` (banner coordinates, PixelMap)
- Python `teleclaude/cli/tui/animation_colors.py` (palettes)

**Outputs**:

- `AnimationEngine` class with play/stop/update/getColor methods
- Double-buffering: back buffer receives new frame, swap on update
- Priority system: PERIODIC < ACTIVITY < MANUAL
- 3 trigger types with start/stop lifecycle

**Acceptance Criteria**:

- [ ] Engine runs at configurable FPS (default 10)
- [ ] Higher-priority animations interrupt lower
- [ ] Queue system (max 5 per target) for lower-priority
- [ ] Pixel map matches Python banner/logo coordinates exactly
- [ ] All 6 animation palettes ported
- [ ] Unit tests for engine, priority, and triggers

**Key Details**:

- Python banner: 67x6 pixels (BIG_BANNER_WIDTH x BIG_BANNER_HEIGHT)
- Python logo: 30x4 pixels (LOGO_WIDTH x LOGO_HEIGHT)
- Letter boundaries defined in BIG_BANNER_LETTERS and LOGO_LETTERS tuples
- PixelMap.get_all_pixels(), get_letter_pixels(), get_row_pixels(), get_column_pixels()
- Config section animations use separate target registry with dynamic width

**Dependencies**: WI-05 (theme tokens for palettes)

---

### WI-09: Animation Algorithms - General

**Stream**: O (Algorithms)
**Size**: Large
**Files to create**:

- `lib/animation/algorithms/spectrum-cycle.ts`
- `lib/animation/algorithms/letter-wave-lr.ts`
- `lib/animation/algorithms/letter-wave-rl.ts`
- `lib/animation/algorithms/line-sweep-tb.ts`
- `lib/animation/algorithms/line-sweep-bt.ts`
- `lib/animation/algorithms/middle-out.ts`
- `lib/animation/algorithms/within-letter-lr.ts`
- `lib/animation/algorithms/within-letter-rl.ts`
- `lib/animation/algorithms/sparkle.ts`
- `lib/animation/algorithms/checkerboard.ts`
- `lib/animation/algorithms/word-split.ts`
- `lib/animation/algorithms/diagonal-dr.ts`
- `lib/animation/algorithms/diagonal-dl.ts`
- `lib/animation/algorithms/letter-shimmer.ts`
- `lib/animation/algorithms/wave-pulse.ts`
- `lib/animation/algorithms/index.ts` (registry)

**Inputs**:

- Python `teleclaude/cli/tui/animations/general.py` (all 15 general animations)

**Outputs**:

- 15 pure functions: `(frame, config, target) => ColorGrid`
- Registry object mapping names to functions

**Acceptance Criteria**:

- [ ] All 15 Python general animations ported as pure TypeScript functions
- [ ] Visual behavior matches Python (same pixel patterns per frame)
- [ ] Each function is stateless (no side effects, no mutation)
- [ ] Unit tests verify frame output for known inputs

**Key Details**:

- Each Python animation class has an `update(frame) -> Dict[Tuple[int,int], int]` method
- Port to: `(frame: number, config: AnimationConfig, target: AnimationTarget) => Map<string, number>`
- ColorGrid key format: `"x,y"` string, value: palette index (-1 = clear)
- Some animations are big-only (supports_small = False)

**Dependencies**: WI-08 (types and pixel map)

---

### WI-10: Animation Algorithms - Agent & Config

**Stream**: O (Algorithms, continued)
**Size**: Large
**Files to create**:

- `lib/animation/algorithms/agent-pulse.ts`
- `lib/animation/algorithms/agent-wave-lr.ts`
- `lib/animation/algorithms/agent-wave-rl.ts`
- `lib/animation/algorithms/agent-line-sweep.ts`
- `lib/animation/algorithms/agent-middle-out.ts`
- `lib/animation/algorithms/agent-sparkle.ts`
- `lib/animation/algorithms/agent-within-letter.ts`
- `lib/animation/algorithms/agent-heartbeat.ts`
- `lib/animation/algorithms/agent-word-split.ts`
- `lib/animation/algorithms/agent-letter-cascade.ts`
- `lib/animation/algorithms/agent-fade-cycle.ts`
- `lib/animation/algorithms/agent-spotlight.ts`
- `lib/animation/algorithms/agent-breathing.ts`
- `lib/animation/algorithms/agent-diagonal.ts`
- `lib/animation/algorithms/config-pulse.ts`
- `lib/animation/algorithms/config-typing.ts`
- `lib/animation/algorithms/config-success.ts`
- `lib/animation/algorithms/config-error.ts`

**Inputs**:

- Python `teleclaude/cli/tui/animations/agent.py` (14 agent animations)
- Python `teleclaude/cli/tui/animations/config.py` (4 config animations)

**Outputs**:

- 18 pure functions following same signature as general algorithms
- Agent animations use 3-color agent palettes
- Config animations use dynamic-width targets

**Acceptance Criteria**:

- [ ] All 14 agent + 4 config animations ported
- [ ] Agent animations receive agent-specific palette
- [ ] Config animations work with variable-width targets
- [ ] Unit tests for each

**Dependencies**: WI-08 (types and pixel map)

---

### WI-11: Animation Algorithms - New

**Stream**: P (New Animations)
**Size**: Medium
**Files to create**:

- `lib/animation/algorithms/matrix-rain.ts`
- `lib/animation/algorithms/rainbow-wave.ts`
- `lib/animation/algorithms/starfield.ts`
- `lib/animation/algorithms/fire.ts`
- `lib/animation/algorithms/plasma.ts`
- `lib/animation/algorithms/game-of-life.ts`
- `lib/animation/algorithms/spiral.ts`
- `lib/animation/algorithms/perlin-noise.ts`
- `lib/animation/algorithms/ripple.ts`
- `lib/animation/algorithms/lightning.ts`

**Inputs**: Algorithm descriptions in requirements.md

**Outputs**:

- 10 new pure animation functions
- All follow same `AnimationAlgorithm` signature

**Acceptance Criteria**:

- [ ] Each animation produces visually distinct, interesting output
- [ ] All are pure functions (no side effects)
- [ ] Performance: each frame < 1ms computation
- [ ] Unit tests for deterministic frame output

**Dependencies**: WI-08 (types and pixel map)

---

## Phase 3: Terminal Components

Depends on Phase 1 completion (store, API, tree, theme, keys, utils).

---

### WI-12: Ink App Shell

**Stream**: H (Layout)
**Size**: Medium
**Files to create**:

- `cli/index.tsx` - Entry point (renders root Ink component)
- `cli/app.tsx` - Root component with fullscreen, view switching, WebSocket
- `cli/components/layout/Banner.tsx` - ASCII art banner (animated)
- `cli/components/layout/TabBar.tsx` - Tab switcher (Sessions/Preparation/Configuration)
- `cli/components/layout/Footer.tsx` - Status bar with agent pills, controls help
- `cli/components/layout/Notification.tsx` - Toast notification overlay
- `cli/components/layout/ViewContainer.tsx` - View router based on activeTab

**Inputs**:

- Python `teleclaude/cli/tui/app.py` (main loop, view switching, banner)
- WI-02 (store), WI-06 (key bindings)

**Outputs**:

- Working Ink app that renders in fullscreen mode
- Tab switching with keyboard
- Banner renders (static initially, animated later)
- Footer shows connected state, active keys

**Acceptance Criteria**:

- [ ] `npx tsx cli/index.tsx` renders fullscreen terminal UI
- [ ] Tab switching with 1/2/3 keys
- [ ] Banner displays "TELECLAUDE" text
- [ ] Footer shows key hints for active view
- [ ] `q` exits cleanly
- [ ] Notification appears on WebSocket connect/disconnect

**Dependencies**: WI-01, WI-02, WI-06

---

### WI-13: Tmux Pane Manager

**Stream**: Q (Tmux)
**Size**: Large
**Files to create**:

- `cli/lib/tmux.ts` - Core tmux wrapper (exec commands, check availability)
- `cli/lib/tmux/layout.ts` - Layout grid system (1x1, 1x2, 2x2, 2x3)
- `cli/lib/tmux/colors.ts` - Agent-specific pane background colors
- `cli/lib/tmux/ssh.ts` - Remote session support (SSH + env forwarding)

**Inputs**:

- Python `teleclaude/cli/tui/pane_manager.py` (all tmux logic)

**Outputs**:

- `TmuxPaneManager` class with applyLayout, showSession, hideSessions
- Layout signature caching
- Agent-specific background colors per pane
- Remote SSH session attachment

**Acceptance Criteria**:

- [ ] Layout grids: 1x1, 1x2, 2x2, 2x3 match Python output
- [ ] Only rebuilds layout when signature changes
- [ ] Agent background colors applied correctly (claude=warm, gemini=purple, codex=teal)
- [ ] Remote sessions open SSH connection with proper env
- [ ] Graceful degradation when not in tmux
- [ ] Pane-to-session mapping for reverse sync
- [ ] Unit tests for layout calculation (mock execSync)

**Key Details**:

- Python `pane_manager.py` is 960 lines. Port the layout logic, not the curses rendering.
- Layout strategy: TUI pane on left, session panes on right
- Grid calculation: divide right portion into rows x cols
- Use `tmux split-window`, `tmux select-layout`, `tmux resize-pane`
- Background color: `tmux select-pane -t X -P 'bg=colorhex'`
- SSH: `tmux new-window ssh user@host -t 'tmux attach -t session'`

**Dependencies**: WI-05 (theme for agent colors)

---

### WI-14: Terminal Hooks

**Stream**: M (Hooks)
**Size**: Medium
**Files to create**:

- `cli/hooks/useKeyBindings.ts` - Global + view-specific key handler
- `cli/hooks/useWebSocket.ts` - WebSocket subscription + event dispatch
- `cli/hooks/useTmux.ts` - Tmux pane operations
- `cli/hooks/useTimers.ts` - Streaming safety, viewing timer, heal timer
- `cli/hooks/useScrollable.ts` - Scroll offset management
- `cli/hooks/useDoublePress.ts` - Wraps gesture state machine

**Inputs**:

- WI-01 (API client), WI-02 (store), WI-04 (gesture), WI-06 (bindings)

**Outputs**:

- React hooks for terminal-specific behavior
- All hooks follow standard React cleanup patterns

**Acceptance Criteria**:

- [ ] `useKeyBindings` handles global + view-specific keys via Ink's `useInput`
- [ ] `useWebSocket` connects, subscribes, dispatches events to store
- [ ] `useTmux` provides attach/focus/detach operations
- [ ] `useTimers` manages streaming safety (30s), viewing (auto-close preview), heal (5s reconnect)
- [ ] `useScrollable` auto-scrolls to keep selected item visible
- [ ] `useDoublePress` integrates gesture state machine with `useInput`
- [ ] All hooks clean up on unmount

**Dependencies**: WI-01, WI-02, WI-04, WI-06, WI-13

---

### WI-15: Session View Components

**Stream**: I (Session Nodes)
**Size**: Large
**Files to create**:

- `cli/components/sessions/SessionsView.tsx` - Main sessions view
- `cli/components/sessions/TreeContainer.tsx` - Scrollable tree renderer
- `cli/components/sessions/nodes/ComputerNode.tsx` - Computer header row
- `cli/components/sessions/nodes/ProjectNode.tsx` - Project header row
- `cli/components/sessions/nodes/SessionNode.tsx` - Session with header + detail
- `cli/components/sessions/nodes/SessionHeader.tsx` - Agent badge, mode, title
- `cli/components/sessions/nodes/SessionDetail.tsx` - Timestamp, session ID
- `cli/components/sessions/nodes/InputLine.tsx` - Input highlight line
- `cli/components/sessions/nodes/OutputLine.tsx` - Output highlight line
- `cli/components/sessions/micro/Badge.tsx` - Agent type badge
- `cli/components/sessions/micro/AgentMode.tsx` - fast/med/slow indicator
- `cli/components/sessions/micro/Subdir.tsx` - Subdir path label
- `cli/components/sessions/micro/Title.tsx` - Session title text

**Inputs**:

- Python `teleclaude/cli/tui/views/sessions.py:_build_session_row_model()` (render logic)
- WI-02 (store), WI-03 (tree), WI-05 (theme), WI-14 (hooks)

**Outputs**:

- Complete sessions view matching Python TUI layout
- Tree with computer -> project -> session hierarchy
- Expandable/collapsible sessions with detail rows
- Input/output highlight lines with agent colors
- Sticky pin indicator

**Acceptance Criteria**:

- [ ] Tree renders computer -> project -> session hierarchy
- [ ] Selected item highlighted
- [ ] Sticky sessions show pin indicator
- [ ] Collapsed sessions hide detail rows
- [ ] Input/output highlights show with correct agent colors
- [ ] Last output summary truncated to width
- [ ] Scroll works with large lists (50+ sessions)
- [ ] Component tests with Ink Testing Library

**Key Details**:

- Python `_build_session_row_model` (sessions.py:2233-2418) is the render template
- Each session row: `[indent] [sticky?] [collapse?] [badge] [mode] [subdir] [title]`
- Detail rows: timestamp, session ID, input highlight, output highlight
- Use `<Box>` for layout, `<Text>` with chalk colors
- Scrollable: only render visible items (window of ~50)

**Dependencies**: WI-02, WI-03, WI-05, WI-14

---

### WI-16: Preparation View Components

**Stream**: J (Prep Nodes)
**Size**: Medium
**Files to create**:

- `cli/components/preparation/PreparationView.tsx` - Main preparation view
- `cli/components/preparation/TreeContainer.tsx` - Todo tree renderer
- `cli/components/preparation/nodes/TodoNode.tsx` - Todo item with status
- `cli/components/preparation/nodes/TodoHeader.tsx` - Todo name + status badge
- `cli/components/preparation/nodes/TodoStatusBadge.tsx` - Phase status indicators
- `cli/components/preparation/nodes/FileNode.tsx` - File path leaf node

**Inputs**:

- Python `teleclaude/cli/tui/views/preparation.py` (1595 lines)
- WI-02 (store), WI-03 (tree), WI-05 (theme)

**Outputs**:

- Todo tree view with project -> todo -> file hierarchy
- Expandable todos with phase status (build, review, docstrings, snippets)
- DOR score display

**Acceptance Criteria**:

- [ ] Project -> todo -> file tree renders
- [ ] Todo expand/collapse with Space
- [ ] Phase statuses (pending/complete/approved/changes_requested) shown
- [ ] DOR score displayed for ready items
- [ ] File nodes show relative path
- [ ] Component tests

**Dependencies**: WI-02, WI-03, WI-05

---

### WI-17: Configuration View Components

**Stream**: K (Config)
**Size**: Medium
**Files to create**:

- `cli/components/configuration/ConfigurationView.tsx` - Main config view
- `cli/components/configuration/SubTabBar.tsx` - Subtab switcher
- `cli/components/configuration/AdaptersTab.tsx` - Adapters config
- `cli/components/configuration/PeopleTab.tsx` - People management
- `cli/components/configuration/NotificationsTab.tsx` - Notification settings

**Inputs**:

- Python `teleclaude/cli/tui/views/config.py`
- WI-02 (store), WI-01 (API client for settings)

**Outputs**:

- Configuration view with subtab navigation
- Each tab shows relevant settings/data

**Acceptance Criteria**:

- [ ] Subtab bar with keyboard navigation (left/right)
- [ ] Adapters tab shows adapter list with status
- [ ] People tab shows people list
- [ ] Notifications tab shows notification settings
- [ ] Settings patch via API on change

**Dependencies**: WI-01, WI-02

---

### WI-18: Modal Components

**Stream**: L (Modals)
**Size**: Medium
**Files to create**:

- `cli/components/modals/StartSessionModal.tsx` - New session creation form
- `cli/components/modals/ConfirmModal.tsx` - Generic confirm/cancel dialog
- `cli/components/modals/inputs/AgentSelector.tsx` - Agent radio selection
- `cli/components/modals/inputs/ModeSelector.tsx` - Thinking mode selection
- `cli/components/modals/inputs/PromptInput.tsx` - Text input for initial prompt

**Inputs**:

- Python `teleclaude/cli/tui/views/sessions.py` (session creation flow)
- WI-01 (API client)

**Outputs**:

- Start session modal with agent/mode/prompt fields
- Tab-based field navigation
- Submit creates session via API
- Confirm modal for destructive actions (end session)

**Acceptance Criteria**:

- [ ] Modal renders as overlay (bordered box)
- [ ] Tab cycles through fields
- [ ] Enter submits form
- [ ] Escape cancels modal
- [ ] Agent selector: claude/gemini/codex with radio buttons
- [ ] Mode selector: fast/med/slow
- [ ] Prompt input accepts multi-line text
- [ ] Confirm modal: Yes/No with Enter/Escape
- [ ] Component tests

**Dependencies**: WI-01, WI-12 (app shell for modal mounting)

---

### WI-19: Terminal Animation Renderer

**Stream**: R (Animation Rendering)
**Size**: Medium
**Files to create**:

- `cli/components/animation/useAnimation.ts` - Animation engine hook
- `cli/components/animation/PixelCanvas.tsx` - Braille-character renderer (drawille + chalk)
- `cli/components/animation/AnimatedBanner.tsx` - Animated banner component

**Inputs**:

- WI-08 (animation engine), WI-09/10/11 (algorithms), WI-05 (theme)

**Outputs**:

- `useAnimation` hook manages engine lifecycle
- `PixelCanvas` renders ColorGrid as braille characters with colors
- `AnimatedBanner` integrates engine with banner display

**Acceptance Criteria**:

- [ ] Banner animates with periodic trigger (every 60s)
- [ ] Agent activity triggers agent-colored animation
- [ ] Braille characters render at 2x4 sub-pixel resolution
- [ ] Colors applied per-pixel via chalk
- [ ] Animation stops cleanly on unmount
- [ ] Performance: no frame drops at 10 FPS

**Dependencies**: WI-08, WI-09, WI-10 (at least some algorithms)

---

### WI-20: Persistence Layer

**Stream**: S (Persistence)
**Size**: Small
**Files to create**:

- `cli/lib/persistence.ts` - Load/save state file with atomic write

**Inputs**:

- Python `teleclaude/cli/tui/state_store.py` (load_sticky_state, save_sticky_state)

**Outputs**:

- `loadTuiState()` - Read `~/.teleclaude/tui_state.json`
- `saveTuiState(state)` - Atomic write with temp + rename + flock

**Acceptance Criteria**:

- [ ] Loads all fields: sticky_sessions, collapsed, highlights, preview, animation_mode, expanded_todos
- [ ] Atomic write: temp file + `fs.rename`
- [ ] Advisory locking via `fs.flock` (best-effort)
- [ ] Handles missing file, corrupt JSON, missing fields gracefully
- [ ] Debounced writes (1s) to reduce I/O

**Dependencies**: WI-02 (store shape for serialization)

---

### WI-21: Session Launcher

**Stream**: T (Session)
**Size**: Medium
**Files to create**:

- `lib/session/launcher.ts` - Session creation orchestration
- `lib/session/agents.ts` - Agent availability check

**Inputs**:

- Python `teleclaude/cli/tui/views/sessions.py` (session start flow)
- WI-01 (API client), WI-13 (tmux)

**Outputs**:

- `launchSession(params)` - Create session via API + attach tmux pane
- `checkAgentAvailability()` - Query daemon for agent status

**Acceptance Criteria**:

- [ ] Creates session via API POST
- [ ] Attaches tmux pane for new session
- [ ] Checks agent availability before showing selector
- [ ] Handles errors (daemon down, tmux unavailable)
- [ ] Returns session info on success

**Dependencies**: WI-01, WI-13

---

## Phase 4: Integration & Testing

Depends on Phase 3 completion. Final assembly and verification.

---

### WI-22: Integration Wiring

**Stream**: U (Integration)
**Size**: Large
**Files to modify**:

- `cli/app.tsx` - Wire WebSocket -> store, tmux sync, timers, animation
- `frontend/package.json` - Add CLI dependencies and scripts
- `frontend/tsconfig.json` - Add CLI paths

**Inputs**: All previous work items

**Outputs**:

- Fully wired Ink terminal app
- `pnpm run cli` script to launch
- WebSocket events flow through to UI updates
- Tmux panes sync with tree selection
- Animations trigger on events

**Acceptance Criteria**:

- [ ] `pnpm run cli` launches fullscreen TUI
- [ ] Connects to daemon WebSocket on start
- [ ] Sessions appear in tree from WebSocket events
- [ ] Selecting session opens tmux preview pane
- [ ] Double-press toggles sticky
- [ ] New session modal creates real session
- [ ] Agent activity triggers animation + highlight
- [ ] State persists across restarts
- [ ] All keyboard bindings work
- [ ] Clean exit on `q`

**Dependencies**: All WI-01 through WI-21

---

### WI-23: Web Animation Renderer

**Stream**: V (Web Animation)
**Size**: Small
**Files to create**:

- `app/components/animation/CanvasAnimation.tsx` - Canvas-based web renderer

**Inputs**:

- WI-08 (animation engine), WI-05 (theme CSS variables)

**Outputs**:

- React component that renders animations on HTML canvas
- Same algorithms, different renderer

**Acceptance Criteria**:

- [ ] Canvas renders animation grid as colored pixels
- [ ] Uses CSS custom properties for theme
- [ ] requestAnimationFrame for smooth rendering
- [ ] Responsive to container size

**Dependencies**: WI-08

---

### WI-24: Test Suite

**Stream**: W (Testing)
**Size**: Large
**Files to create**:

- `lib/__tests__/reducer.test.ts` - All 25 intents
- `lib/__tests__/tree-builder.test.ts` - Tree construction
- `lib/__tests__/gesture.test.ts` - Double-press state machine
- `lib/__tests__/animation-engine.test.ts` - Engine lifecycle
- `cli/__tests__/sessions-view.test.tsx` - Ink component tests
- `cli/__tests__/app.test.tsx` - Integration test

**Inputs**: All implementations

**Outputs**:

- Comprehensive test suite
- `pnpm test` passes all

**Acceptance Criteria**:

- [ ] Reducer: every intent type has at least one test
- [ ] Tree: builds correctly with various data shapes
- [ ] Gesture: timing-based tests with fake timers
- [ ] Engine: priority, queue, double-buffer
- [ ] SessionsView: renders tree, handles keys
- [ ] App: mounts, connects, renders

**Dependencies**: All implementations

---

## Summary

| Phase          | Work Items          | Parallel Agents | Blocking           |
| -------------- | ------------------- | --------------- | ------------------ |
| 1: Foundation  | WI-01 through WI-07 | 7               | None               |
| 2: Animation   | WI-08 through WI-11 | 3-4             | WI-05 for palettes |
| 3: Components  | WI-12 through WI-21 | 8-10            | Phase 1            |
| 4: Integration | WI-22 through WI-24 | 3               | Phase 1+2+3        |

**Total**: 24 work items, ~100 files, 13+ parallel work streams.

**Critical path**: WI-01 + WI-02 -> WI-14 -> WI-15 -> WI-22

**Estimated team size**: 7-10 parallel agents for maximum throughput.
