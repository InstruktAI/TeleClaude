# Implementation Plan: animations-full-color

## Overview

We need to inject serious creativity into the TUI animations. The current setup is limited to basic 16-color ANSI palettes. We will build a HEX-color interpolation engine and use it to power 15 brand new, highly expressive animations (clouds, lava, aurora, cyberpunk, etc.).

## Phase 1: Color Interpolation & Palette Upgrade

### Task 1.1: Build `GradientPalette` and Utilities

**File(s):** `teleclaude/cli/tui/animation_colors.py`

- [x] Implement `hex_to_rgb(hex_str)` and `rgb_to_hex(r, g, b)` (or use the existing `_hex_to_rgb` and `_rgb_to_hex`).
- [x] Create a `interpolate_color(c1, c2, factor)` function that takes two hex strings and a float `0.0-1.0` and returns the blended hex string.
- [x] Create a `MultiGradient` class that takes a list of hex color stops and can return an interpolated color for any float `0.0-1.0` along the gradient line.

## Phase 2: The Creative Animation Suite

### Task 2.1: Implement 15 New Animations

**File(s):** `teleclaude/cli/tui/animations/general.py`

Implement the following classes, inheriting from `Animation`. Use math (sine, modulo, distance, random) to achieve the effects:

1. `SunsetGradient`: Left-to-right or bottom-to-top gradient mapping.
2. `CloudsPassing`: Background `#87CEEB`, moving white blobs (use coordinate clustering).
3. `FloatingBalloons`: Random vertical columns moving up with grouped colors.
4. `NeonCyberpunk`: Diagonal sweeping bands of Cyan and Magenta.
5. `AuroraBorealis`: Vertical sine-wave based horizontal sweep of greens and purples.
6. `LavaLamp`: Slower vertical sine waves mixing red and orange.
7. `StarryNight`: Mostly dark blue `#0B1021`, with `random.random() < 0.05` lighting up white/yellow.
8. `MatrixRain`: Vertical trails of bright green `#39FF14` fading upwards.
9. `OceanWaves`: Horizontal sine waves of teal and aqua.
10. `FireBreath`: Random flicker favoring bottom rows for reds/yellows, top rows for greys/blacks.
11. `SynthwaveWireframe`: Static gradient based purely on the `y` coordinate (row).
12. `PrismaticShimmer`: High-frequency random color assignment from a bright jewel-tone palette.
13. `BreathingHeart`: Distance-based gradient from the center `(width/2, height/2)` pulsing over time.
14. `IceCrystals`: Edge-distance based transition from blue to white.
15. `Bioluminescence`: Independent moving "agents" or dots of blue `#4682B4` leaving tiny fading trails.

### Task 2.2: Registration

**File(s):** `teleclaude/cli/tui/animations/general.py`

- [x] Add all 15 classes to the `GENERAL_ANIMATIONS` list, replacing or supplementing the old ones.

---

## Phase 3: Validation

### Task 3.1: Tests and TUI Check

- [x] Run `make test`.
- [x] Run `telec` and ensure the banner cycles through or triggers these animations flawlessly, exhibiting rich 24-bit colors.

### Task 3.2: Quality Checks

- [x] Run `make lint`.
- [x] Ensure all implementation tasks are ticked `[x]`.

---

## Phase 4: Review Readiness

- [x] Confirm requirements are met and all 15 creative animations are built.
- [x] Confirm implementation tasks are marked `[x]`.
