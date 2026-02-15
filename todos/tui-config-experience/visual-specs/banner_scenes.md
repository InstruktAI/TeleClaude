# Banner Scene Animations — Concept Doc

## Philosophy

The TELECLAUDE banner is a playground. These animations bring it to life beyond
color cycling — they add movement, character, and surprise. The aesthetic is
C64 demoscene: raster effects, scrollers, pixel art movement, plasma.

## Category A: Color-Only Effects (banner_scenes.py — prototyped)

These work within the current Animation ABC (color mapping only).

| Animation    | Mood               | When to use         | Mode            |
| ------------ | ------------------ | ------------------- | --------------- |
| PlasmaWave   | Mesmerizing, alive | Party background    | party           |
| RasterBars   | Retro, CRT         | Party accent        | party           |
| Starfield    | Calm, spacious     | Periodic background | periodic, party |
| ShootingStar | Brief, magical     | Periodic accent     | periodic, party |

## Category B: Character Scene Animations (NEED ENGINE EXTENSION)

These require rendering actual characters at screen positions, not just color
overlays. They target the **tab bar line** (row 3 of TabBar rendering).

### Technical Requirement

The current Animation ABC returns `Dict[(x,y), int]` — color pairs only.
Character scenes need to inject characters at specific screen positions.

**Proposed approach:** Separate `SceneOverlay` system (Option 2 from Artist/Builder B discussion):

- Independent from Animation ABC — does not change existing contract
- SceneOverlay class manages position, character, color, z-level per frame
- Tab bar renderer consults the overlay during its render pass
- Overlay respects z-levels: z=3 for scene chars, z=2 for inactive tabs, z=4 for active tab

### B1: Bicycle Rider

```
Single-line ASCII:  ♦⊙─⊙  (4 chars, moves right)
Color: spectrum cycling, rainbow trail that fades 3 chars behind
Speed: 2 chars/frame at 100ms = ~4s to cross 82-char width
Depth: z=3 (in front of inactive tabs, behind active tab)
Frequency: Random, every 3-5 min in party mode
```

### B2: Car Drive

```
Single-line ASCII:  ═[▪]═  (5 chars, moves LEFT — opposite of bike)
Color: warm tones (gold/orange)
Speed: 3 chars/frame — slightly faster than bike
Can chain with bicycle for near-miss encounter
```

### B3: Running Pixel Cat

```
Single-line ASCII:  =^.^=  (5 chars, moves right)
Alt frame:          =^·^=  (dot changes for run cycle)
Color: warm orange/gold (xterm 178/180)
Leaves paw-print dots (·) that fade after 3 frames
Speed: 2 chars/frame
```

### B4: Scrolling Message (Demoscene Scroller)

```
Message: "WELCOME TO TELECLAUDE ··· CONFIGURATION IS FUN ··· "
Scrolls left continuously across tab bar line
Each character cycles through spectrum colors
Speed: 1 char/frame at 60ms for smooth scroll
```

Most authentic C64 demoscene element. This one should feel like a demo intro.

## Category C: Banner Transformations (banner_scenes.py — prototyped)

| Animation         | Use                           | Duration |
| ----------------- | ----------------------------- | -------- |
| BannerScrollOut   | Tab transition (exit)         | 1.5s     |
| BannerDropIn      | Tab entrance (config tab)     | 1.5s     |
| PixelDisintegrate | Dramatic entrance/celebration | 4.5s     |
| BannerGlitch      | Error state                   | 2s       |
| MarqueeWrap       | Party background (continuous) | infinite |

## Mode Assignments

| Mode     | Active Animations                                                        |
| -------- | ------------------------------------------------------------------------ |
| OFF      | None                                                                     |
| PERIODIC | Starfield, ShootingStar (rotated)                                        |
| PARTY    | All of the above + PlasmaWave, RasterBars, MarqueeWrap, character scenes |
