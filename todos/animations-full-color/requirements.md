# Requirements: animations-full-color

## Goal

- Ditch the legacy 16-color spectrum in TUI animations and fully embrace the 24-bit TrueColor (HEX colors) available via the Textual library.
- Create a beautiful, dynamic, and massive suite of new, highly visual gradient and particle-based animations. We want a *shitload* of visually stunning new effects that bring the TUI banner and logo to life.

## Scope

### In scope:
- **Color Engine Upgrade**: Implement `GradientPalette` and HEX interpolation logic in `teleclaude/cli/tui/animation_colors.py`. All color output should support arbitrary `#RRGGBB` formatting.
- **Creative Suite of Animations**: Add at least 15 new, distinct, highly visual animations to `teleclaude/cli/tui/animations/general.py`.
- **The Effects**:
  1. **Sunset Gradient**: Smooth transition from deep orange `#FF4500` to yellow `#FFD700` and magenta `#FF00FF` sweeping across the text.
  2. **Clouds Passing**: A light sky blue base `#87CEEB` with clusters of fluffy white `#FFFFFF` pixels drifting horizontally.
  3. **Floating Balloons**: Distinct, brightly colored clusters (red `#FF3366`, yellow `#FFD700`, green `#33CC66`) spawning at the bottom and floating upwards.
  4. **Neon Cyberpunk**: High-contrast cyan `#00FFFF` and magenta `#FF00FF` pulsing in diagonal waves.
  5. **Aurora Borealis**: Wavy, organic vertical pulses of emerald green `#50C878`, dark blue `#00008B`, and purple `#800080`.
  6. **Lava Lamp**: Slow, morphing, amorphous blobs of bright red `#FF4500` and dark orange `#FF8C00` rising and falling.
  7. **Starry Night**: Deep midnight blue background `#0B1021` with sparse, blinking white and pale yellow pixels mimicking twinkling stars.
  8. **Matrix Rain**: Bright neon green `#39FF14` "raindrops" falling in vertical columns, leaving a fading trail of dark green `#006400`.
  9. **Ocean Waves**: Deep teal `#008080`, aqua `#00FFFF`, and navy `#000080` sweeping horizontally with a sine-wave mathematical displacement.
  10. **Fire Breath**: Flickering orange, yellow, and red pixels heavily concentrated at the bottom of the characters, turning to dark ash/grey and dissipating near the top.
  11. **Synthwave Wireframe**: A glowing magenta sun horizon effect at the bottom, fading to dark purple skies at the top.
  12. **Prismatic Shimmer**: Fast, chaotic sparkling of bright jewel tones (ruby, sapphire, emerald) across individual pixels.
  13. **Breathing Heart**: Gentle, slow rhythmic swelling of crimson `#DC143C` to dark maroon `#8B0000` radiating from the center outward.
  14. **Ice Crystals**: Frosty light blue `#E0FFFF` creeping in from the outer edges, eventually turning the whole word solid white before shattering.
  15. **Bioluminescence**: Pitch black base with glowing, trailing spots of neon blue `#4682B4` moving randomly like fireflies or deep-sea creatures.

### Out of scope:
- Changing the ASCII text of the banner or logo itself.
- Restructuring the core `AnimationEngine` threading model; it already ticks fast enough, just provide it the right colors.

## Success Criteria

- [ ] `animation_colors.py` supports seamless Hex color generation and linear/radial gradients.
- [ ] At least 15 new animation classes (as described above) are implemented in `teleclaude/cli/tui/animations/general.py`.
- [ ] The `GENERAL_ANIMATIONS` list registers all of these new beautiful effects.
- [ ] The TUI banner displays these effects flawlessly in 24-bit TrueColor.

## Constraints

- Keep frame computation fast; avoid doing heavy image processing. Use simple math (sine waves, modulos, random choices) to generate the effects.

## Risks

- Generating complex gradient maps on the fly could impact CPU if not optimized. Cache gradients or keep math simple.
