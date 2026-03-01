# TUI Animation Specification: The Cinematic Rooftop

This document defines the architectural and physical model for the TeleClaude TUI animation suite. It transforms the banner area from a flat text box into a multi-layered, reactive physical environment.

## 1. Physical Architecture

The header is conceptually the **rooftop of the TeleClaude building**.

### The Billboard

- **The Plate:** A rectangular mounting surface shifted **+1 character to the right** to provide a consistent margin.
- **Support Structure:** Two vertical metallic pipes rendered directly beneath the letters **'E'** and **'D'**, grounding the sign to the roof.
- **Ghost Outlines:** Tab panes and adjacent UI elements have low-opacity (15%) "ghost" borders to define the building's skeletal frame.

### Material Physics

| Property                      | Value | Description                                                                             |
| :---------------------------- | :---- | :-------------------------------------------------------------------------------------- |
| **Reflectivity ($\alpha$)**   | 0.30  | The billboard plate reflects 30% of external light sources.                             |
| **Luminescence ($\beta$)**    | 1.00  | Neon tubes emit light at 100% intensity; they are never gray during active effects.     |
| **Shadow Opacity ($\gamma$)** | 0.60  | Environmental shadows (birds/entities) dim the underlying layers by 40% (floor at 60%). |

## 2. Atmospheric Model

Lighting and entities change based on the system `theme_mode`.

### Day Mode (Atmospheric)

- **Primary Source:** High Sun at a golden angle (Light from Above).
- **Shadow Vector:** Downward and slightly diagonal.
- **Entities:** Birds flapping in the foreground (Layer 2).
- **Sky:** Fluffy clouds drifting behind the billboard (Layer -1).

### Night Mode (Nightmare)

- **Primary Source:** Rooftop searchlights (Light from Below).
- **Shadow Vector:** Upward and backward onto the building structure.
- **Entities:** Batman-signal silhouettes and digital neon surges.
- **Sky:** Twinkling multi-colored stars (Layer -1).

## 3. Z-Layer Composition

The engine flattens layers in the following order:

1.  **Layer -1 (Sky):** Background effects. Occluded by the Billboard Plate.
2.  **Layer 0 (Structure):** The physical Billboard Plate and metallic pipes.
3.  **Layer 1 (Neon):** The TeleClaude letters. Character cells are treated as light-emitting tubes.
4.  **Layer 2 (Entities):** Foreground objects. These cast **Projective Shadows** that dim all layers beneath them.

## 4. Animation Catalog

### Environmental Events (Reflective)

| Animation          | Mode  | Surface       | Behavior                                               |
| :----------------- | :---- | :------------ | :----------------------------------------------------- |
| `SearchlightSweep` | Night | Plate + Tubes | Upward Batman silhouette shadow + high-intensity beam. |
| `HighSunBird`      | Day   | Plate + Tubes | Foreground entity casting downward diagonal shadows.   |
| `CloudsPassing`    | Day   | Sky           | Fluffy background occlusion behind the billboard.      |
| `StarryNight`      | Night | Sky           | Twinkling star field behind the billboard.             |

### Neon Surge Effects (Internal)

_Heuristic: In Neon mode, letters are always colored. There are no gray gaps._

| Animation             | Mode  | Behavior                                                                 |
| :-------------------- | :---- | :----------------------------------------------------------------------- |
| `CinematicPrismSweep` | Both  | Volumetric morphing beam; pivoting angle (30° to 60°); hue-morphing.     |
| `GradientSweep (V/H)` | Both  | Replaces crude scanlines. Volumetric power surge with soft falloff.      |
| `GlitchedNeonRain`    | Night | Digital rain that triggers brightness flares upon contact with neon gas. |
| `AtmosphericFire`     | Night | Industrial flare; Yellow core at base, Red flicker at tips.              |
| `AuroraBorealis`      | Night | Organic vertical pulses with procedural hue-shifting.                    |
| `SunsetGradient`      | Day   | Horizontal atmospheric color wash with organic modulation.               |
| `WavePulse`           | Both  | High-voltage traveling surge with trailing intensity decay.              |

## 5. Organic Modulation (Living Parameters)

Animations do not use fixed speeds. Every instance follows an **Organic Modulation Graph** over its 12s – 20s lifespan:

- **Initialization (0-4s):** Slow atmospheric crawl (0.3x).
- **Active Peak (4-12s):** Surge to maximum intensity and speed (0.8x).
- **Landing (12-20s):** Long, slow settling drift (0.5x -> 0.3x).

## 6. Contrast & Readability Mandate

- **The Floor:** In Dark Mode, non-shadow colors are mathematically boosted to a **minimum 120 RGB** average.
- **Transparency:** Inactive animation areas must return a **transparent sentinel (-1)** to preserve the physical billboard gray and default letter gray.
- **No Overwrites:** No animation is allowed to paint the background black or gray; it must only modify the "light" state of the characters or the "reflection" state of the plate.
