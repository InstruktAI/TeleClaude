# TELECLAUDE Banner Animation Matrix (Character-as-Pixel Model)

## Physical Constraints

### Big ASCII Banner

- **Grid**: ~80-90 characters wide × 5 lines tall
- **Letter size**: ~8-9 characters wide per letter
- **Total letters**: 10 (T-E-L-E-C-L-A-U-D-E)
- **Pixel unit**: Each ASCII character is one pixel
- **Animation capabilities**: Full directional sweeps, within-letter animations, middle-out vertical

### Small ASCII Logo

- **Grid**: 39 characters wide × 3 lines tall
- **Total letters**: 10 (T-E-L-E-C-L-A-U-D-E)
- **Pixel unit**: Each ASCII character is one pixel
- **Animation capabilities**: Color changes only, letter-level waves, line sweeps (3 lines max)
- **Limitations**: No diagonal sweeps, no middle-out (only 3 lines)

## Animation Philosophy

**Character-as-Pixel Model:**

- Each ASCII character cell is an atomic unit with ONE color at a time
- Animation = changing which color each character cell has over time
- No sub-character gradients or effects

**Color Palette Rules:**

- **Periodic Random Trigger**: Uses full rainbow/spectrum palette
- **Agent Activity Trigger**: Uses agent-specific palette (Muted, Normal, Highlight)
- Each animation decides which subset of available colors to use

**Within-Letter Color Transitions:**

- **Horizontal**: Left-to-right or right-to-left through character columns
- **Vertical**: Top-to-bottom or bottom-to-top through the 5 lines (big) or 3 lines (small)
- **Middle-outward**: From middle line spreading up and down simultaneously (big banner only)

## GENERAL ANIMATIONS (Periodic Random - Full Color Palette Available)

| #   | Animation Name            | Pattern Description                                                   | Scope                           | Applies To         | Complexity |
| --- | ------------------------- | --------------------------------------------------------------------- | ------------------------------- | ------------------ | ---------- |
| G1  | Full Spectrum Cycle       | All character pixels synchronously cycle through color palette        | All pixels                      | Big + Small        | Low        |
| G2  | Letter Wave (L→R)         | Each letter (all its pixels) lights up sequentially left to right     | Per-letter units                | Big + Small        | Low        |
| G3  | Letter Wave (R→L)         | Each letter lights up sequentially right to left                      | Per-letter units                | Big + Small        | Low        |
| G4  | Within-Letter Sweep (L→R) | Within each letter, pixels sweep horizontally left to right           | Character columns within letter | Big only           | Medium     |
| G5  | Within-Letter Sweep (R→L) | Within each letter, pixels sweep horizontally right to left           | Character columns within letter | Big only           | Medium     |
| G6  | Line Sweep (Top→Bottom)   | All pixels in line 1 change, then line 2, then 3, etc.                | Horizontal lines (rows)         | Big + Small        | Low        |
| G7  | Line Sweep (Bottom→Top)   | All pixels in line 5 change, then 4, then 3, etc.                     | Horizontal lines (rows)         | Big + Small        | Low        |
| G8  | Middle-Out Vertical       | Line 3 changes first, then lines 2&4 simultaneously, then 1&5         | Vertical center expansion       | Big only (5 lines) | Medium     |
| G9  | Word Split Blink          | "TELE" pixels vs "CLAUDE" pixels blink alternately                    | Two word segments               | Big + Small        | Low        |
| G10 | Random Pixel Sparkle      | Random individual character pixels flash random colors from palette   | Random individual pixels        | Big + Small        | High       |
| G11 | Diagonal Sweep (↘)        | Pixels light up in diagonal waves top-left to bottom-right            | Diagonal traversal              | Big only           | Medium     |
| G12 | Diagonal Sweep (↙)        | Pixels light up in diagonal waves top-right to bottom-left            | Diagonal traversal              | Big only           | Medium     |
| G13 | Checkerboard Flash        | Alternating pixels flash in checkerboard pattern (odd/even positions) | Alternating pixel grid          | Big + Small        | Medium     |
| G14 | Letter Shimmer            | Each letter rapidly cycles through different colors independently     | Per-letter, high frequency      | Big + Small        | Medium     |
| G15 | Wave Pulse                | Color wave travels through word with trailing brightness gradient     | Cross-word with decay           | Big + Small        | High       |

## AGENT-SPECIFIC ANIMATIONS (Activity-Triggered - Agent Color Palette: Muted, Normal, Highlight)

| #   | Animation Name            | Pattern Description                                                                | Scope                           | Applies To         | Complexity |
| --- | ------------------------- | ---------------------------------------------------------------------------------- | ------------------------------- | ------------------ | ---------- |
| A1  | Agent Pulse               | All pixels pulse synchronously through 3 agent colors (Muted → Normal → Highlight) | All pixels synchronized         | Big + Small        | Low        |
| A2  | Agent Wave (L→R)          | Letter-by-letter wave using agent color sequence                                   | Per-letter units                | Big + Small        | Low        |
| A3  | Agent Wave (R→L)          | Letter-by-letter wave right-to-left using agent colors                             | Per-letter units                | Big + Small        | Low        |
| A4  | Agent Heartbeat           | All pixels pulse with strong beat (Highlight) then rest (Muted)                    | All pixels binary pulse         | Big + Small        | Low        |
| A5  | Agent Letter Cascade      | Letters light up sequentially, each using one of the 3 agent colors                | Per-letter sequential           | Big + Small        | Medium     |
| A6  | Agent Word Split          | "TELE" and "CLAUDE" alternate between Muted and Normal/Highlight                   | Two word segments               | Big + Small        | Low        |
| A7  | Agent Sparkle             | Random pixels flash with random agent colors                                       | Random individual pixels        | Big + Small        | High       |
| A8  | Agent Fade Cycle          | All pixels smoothly transition Muted ↔ Normal ↔ Highlight                          | All pixels smooth transition    | Big + Small        | Medium     |
| A9  | Agent Line Sweep          | Horizontal lines sweep top-to-bottom with agent color progression                  | Horizontal lines (rows)         | Big + Small        | Medium     |
| A10 | Agent Spotlight           | Bright pixel cluster (Highlight) travels through word, fading edges to Muted       | Moving window with gradient     | Big + Small        | High       |
| A11 | Agent Within-Letter Sweep | Within each letter, pixels sweep L→R or R→L using agent colors                     | Character columns within letter | Big only           | High       |
| A12 | Agent Breathing           | Gentle synchronized pulse of all pixels through agent colors with easing           | All pixels with easing curve    | Big + Small        | Low        |
| A13 | Agent Diagonal Wave       | Diagonal pixel sweep using agent color sequence                                    | Diagonal traversal              | Big only           | Medium     |
| A14 | Agent Middle-Out          | Line 3 changes first (Highlight), then 2&4 (Normal), then 1&5 (Muted)              | Vertical center expansion       | Big only (5 lines) | Medium     |

## TRIGGER MATRIX

| Trigger                     | Frequency                     | Animation Pool           | Color Source                              | Duration    | Interruption                         |
| --------------------------- | ----------------------------- | ------------------------ | ----------------------------------------- | ----------- | ------------------------------------ |
| **Periodic Random**         | Every 60 seconds              | G1-G15 (select 1 random) | Full Rainbow Spectrum                     | 3-8 seconds | Can be interrupted by agent activity |
| **Agent Activity (Claude)** | On WebSocket session activity | A1-A14 (select 1 random) | Claude palette (Muted, Normal, Highlight) | 2-5 seconds | Restarts on each activity pulse      |
| **Agent Activity (Gemini)** | On WebSocket session activity | A1-A14 (select 1 random) | Gemini palette (Muted, Normal, Highlight) | 2-5 seconds | Restarts on each activity pulse      |
| **Agent Activity (Codex)**  | On WebSocket session activity | A1-A14 (select 1 random) | Codex palette (Muted, Normal, Highlight)  | 2-5 seconds | Restarts on each activity pulse      |

## ANIMATION PROPERTIES

Each animation implementation requires:

- **Duration**: How long it runs (seconds)
- **Speed**: Animation frame rate (ms per frame, e.g., 100ms)
- **Direction**: Direction of travel (L→R, R→L, T→B, B→T, Inside-Out, Random)
- **Easing**: Linear, Ease-In, Ease-Out, Ease-In-Out, Bounce
- **Color Selection Strategy**: How colors are picked from available palette
- **Repetitions**: How many times it cycles before stopping

## IMPLEMENTATION NOTES

1. **Pixel Mapping**: Create coordinate system for all character positions in both banners
2. **Color Application**: Each pixel (character position) needs color attribute management
3. **Frame Buffer**: Double-buffer system to avoid flicker during animation updates
4. **Timing Engine**: Async timer/scheduler for animation frames
5. **Activity Detection**: WebSocket event listener to detect agent activity
6. **Animation Queue**: Handle overlapping/interrupting animations
7. **Performance**: Minimize curses redraws, batch color changes per frame
