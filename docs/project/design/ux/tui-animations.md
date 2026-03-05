---
id: 'project/design/ux/tui-animations'
type: 'design'
scope: 'project'
description: 'Physical architecture and animation catalog for the TUI cinematic rooftop banner.'
---

# TUI Animation Specification: The Cinematic Rooftop

## Purpose

Defines the architectural and physical model for the TeleClaude TUI animation suite. It transforms the banner area from a flat text box into a multi-layered, reactive physical environment called "the cinematic rooftop."

### Physical Architecture

The header is conceptually the **rooftop of the TeleClaude building**.

#### The Billboard

- **The Plate:** A rectangular mounting surface shifted **+1 character to the right** to provide a consistent margin.
- **Support Structure:** Two vertical metallic pipes rendered directly beneath the letters **'E'** and **'D'**, grounding the sign to the roof.
- **Ghost Outlines:** Tab panes and adjacent UI elements have low-opacity (15%) "ghost" borders to define the building's skeletal frame.

#### Material Physics

| Property                      | Value | Description                                                                             |
| :---------------------------- | :---- | :-------------------------------------------------------------------------------------- |
| **Reflectivity ($\alpha$)**   | 0.30  | The billboard plate reflects 30% of external light sources.                             |
| **Luminescence ($\beta$)**    | 1.00  | Neon tubes emit light at 100% intensity; they are never gray during active effects.     |
| **Shadow Opacity ($\gamma$)** | 0.60  | Environmental shadows (birds/entities) dim the underlying layers by 40% (floor at 60%). |

### Atmospheric Model

Lighting and entities change based on the system `theme_mode`.

#### Day Mode (Atmospheric)

- **Primary Source:** Quarter sun at top-right corner (bottom-left quarter visible).
- **Shadow Vector:** Downward and slightly diagonal.
- **Entities:** Clouds at weighted depth (far/mid/near), rare UFO as sky entity.
- **Sky:** Gradient from `#87CEEB` to `#C8E8F8`.

#### Night Mode (Nightmare)

- **Primary Source:** Rooftop searchlights (Light from Below).
- **Shadow Vector:** Upward and backward onto the building structure.
- **Entities:** Batman-signal silhouettes and digital neon surges.
- **Sky:** Twinkling stars at Z_STARS (behind celestials), quarter moon at top-right.

### Haze Pipeline

Focus state is centralized via `theme.resolve_haze()`:

- `set_tui_focused(bool)` — called by `app._watch_app_focus()`
- `resolve_haze(hex_color)` — returns color as-is when focused, applies TUI inactive haze when unfocused
- `get_billboard_background()` — adapts to focus state internally

All widgets (banner, tabs, sky entities) use `resolve_haze()` instead of manual focus checks.

### Organic Modulation (Living Parameters)

Animations do not use fixed speeds. Every instance follows an **Organic Modulation Graph** over its 12s – 20s lifespan:

- **Initialization (0-4s):** Slow atmospheric crawl (0.3x).
- **Active Peak (4-12s):** Surge to maximum intensity and speed (0.8x).
- **Landing (12-20s):** Long, slow settling drift (0.5x -> 0.3x).

## Inputs/Outputs

- **Input:** System `theme_mode` (day/night), TUI focus state, terminal width.
- **Output:** Rendered animation layers composited over the banner/header area using Z-level ordering.

## Invariants

1. **Contrast & Readability:** In Dark Mode, non-shadow colors are mathematically boosted to a minimum 120 RGB average.
2. **Transparency:** Inactive animation areas must return a transparent sentinel (-1) to preserve the physical billboard gray and default letter gray.
3. **No Overwrites:** No animation is allowed to paint the background black or gray; it must only modify the "light" state of the characters or the "reflection" state of the plate.
4. **Neon heuristic:** In Neon mode, letters are always colored. There are no gray gaps.

## Primary flows

### Z-Level Composition

Physical Z-levels with 10-unit spacing for intermediate layers (defined in `base.py`):

| Z-Level | Constant          | Purpose                                      |
| :------ | :---------------- | :------------------------------------------- |
| 0       | `Z_SKY`           | Background sky gradient                      |
| 10      | `Z_STARS`         | Twinkling star field (night mode)            |
| 20      | `Z_CELESTIAL`     | Sun/moon quarter disc at top-right           |
| 30      | `Z_CLOUDS_FAR`    | Distant wisps and far clouds                 |
| 40      | `Z_BILLBOARD`     | The physical billboard plate                 |
| 50      | `Z_CLOUDS_MID`    | Mid-depth clouds (show around billboard)     |
| 60      | `Z_TABS_INACTIVE` | Inactive tab bar surfaces                    |
| 70      | `Z_CLOUDS_NEAR`   | Near clouds (show in front of inactive tabs) |
| 80      | `Z_TABS_ACTIVE`   | Active tab (nothing renders in front)        |
| 90      | `Z_FOREGROUND`    | Billboard foreground entities                |

#### Cloud Depth Distribution

Clouds receive weighted Z-levels per size category:

| Size | Category | Z_FAR | Z_MID | Z_NEAR |
| :--- | :------- | :---- | :---- | :----- |
| 0    | Wisps    | 100%  | —     | —      |
| 1    | Puffs    | 80%   | 20%   | —      |
| 2    | Medium   | 30%   | 60%   | 10%    |
| 3    | Cumulus  | 10%   | 50%   | 40%    |

#### UFO Sky Entity

UFO spawns inside GlobalSky (~15% chance per weather cycle) with weighted depth:

- 50% Z_CLOUDS_FAR, 35% Z_CLOUDS_MID, 15% Z_CLOUDS_NEAR

#### Quarter Celestial

Sun (day) and moon (night) render as a quarter disc anchored at the top-right corner. The center is placed at `(term_width-1, -2)` so only the bottom-left quarter is visible. Works at any terminal width.

### Animation Catalog

#### Environmental Events (Reflective)

| Animation          | Mode  | Surface       | Behavior                                               |
| :----------------- | :---- | :------------ | :----------------------------------------------------- |
| `SearchlightSweep` | Night | Plate + Tubes | Upward Batman silhouette shadow + high-intensity beam. |
| `CloudsPassing`    | Day   | Plate + Tubes | Fluffy background occlusion behind the billboard.      |

#### Sky Entities (GlobalSky-managed)

| Entity | Mode  | Behavior                                           |
| :----- | :---- | :------------------------------------------------- |
| Stars  | Night | Twinkle at Z_STARS, behind celestials and clouds   |
| Moon   | Night | Quarter disc at top-right corner, Z_CELESTIAL      |
| Sun    | Day   | Quarter disc at top-right corner, Z_CELESTIAL      |
| Clouds | Day   | Parallax drift at weighted Z-levels (far/mid/near) |
| UFO    | Both  | Rare (~15%), drifts horizontally at weighted depth |

#### Neon Surge Effects (Internal)

| Animation             | Mode  | Behavior                                                                 |
| :-------------------- | :---- | :----------------------------------------------------------------------- |
| `CinematicPrismSweep` | Both  | Volumetric morphing beam; pivoting angle (30° to 60°); hue-morphing.     |
| `GradientSweep (V/H)` | Both  | Replaces crude scanlines. Volumetric power surge with soft falloff.      |
| `GlitchedNeonRain`    | Night | Digital rain that triggers brightness flares upon contact with neon gas. |
| `AtmosphericFire`     | Night | Industrial flare; Yellow core at base, Red flicker at tips.              |
| `AuroraBorealis`      | Night | Organic vertical pulses with procedural hue-shifting.                    |
| `SunsetGradient`      | Day   | Horizontal atmospheric color wash with organic modulation.               |
| `WavePulse`           | Both  | High-voltage traveling surge with trailing intensity decay.              |

## Failure modes

| Scenario                            | Behavior                                                                              |
| ----------------------------------- | ------------------------------------------------------------------------------------- |
| Color falls below minimum RGB floor | Boost algorithm raises value to 120 RGB average minimum in Dark Mode.                 |
| Animation paints background black   | Invariant violation — animation must return transparent sentinel (-1) for inactives.  |
| Focus state inconsistency           | `resolve_haze()` is the single source of truth; widgets must not perform manual checks. |
| Terminal width changes mid-render   | Quarter celestial recalculates center from `term_width-1` on each render pass.        |
