# Demo Plan: animations-full-color

## Medium

CLI / Python

## Observation

1. The `animation_colors.py` module now exposes `hex_to_rgb`, `rgb_to_hex`, `interpolate_color`, and `MultiGradient` for 24-bit TrueColor support.
2. `GENERAL_ANIMATIONS` now contains 30 entries — the original 15 plus 15 new TrueColor animations.
3. Each new animation class is importable and produces per-pixel `#RRGGBB` hex color output.
4. The TUI banner will cycle through all registered animations including the new rich gradient and particle effects.

## Validation Commands

```bash
# Verify color utility functions work correctly
python -c "
from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex, interpolate_color, MultiGradient

# hex_to_rgb / rgb_to_hex round-trip
assert hex_to_rgb('#FF4500') == (255, 69, 0), 'hex_to_rgb failed'
assert rgb_to_hex(255, 69, 0) == '#ff4500', 'rgb_to_hex failed'

# interpolate_color midpoint
mid = interpolate_color('#000000', '#ffffff', 0.5)
r, g, b = hex_to_rgb(mid)
assert 120 <= r <= 136 and 120 <= g <= 136 and 120 <= b <= 136, f'interpolate_color bad midpoint: {mid}'

# MultiGradient single stop
mg1 = MultiGradient(['#FF0000'])
assert mg1.get(0.0) == '#ff0000', 'MultiGradient single stop failed'

# MultiGradient two stops
mg2 = MultiGradient(['#000000', '#ffffff'])
assert mg2.get(0.0) == '#000000', 'MultiGradient start failed'
assert mg2.get(1.0) == '#ffffff', 'MultiGradient end failed'
mid2 = mg2.get(0.5)
r2, g2, b2 = hex_to_rgb(mid2)
assert 120 <= r2 <= 136, f'MultiGradient midpoint bad: {mid2}'

print('Color utilities: OK')
"
```

```bash
# Verify all 15 new animation classes are importable and registered
python -c "
from teleclaude.cli.tui.animations.general import (
    GENERAL_ANIMATIONS,
    SunsetGradient, CloudsPassing, FloatingBalloons, NeonCyberpunk,
    AuroraBorealis, LavaLamp, StarryNight, MatrixRain, OceanWaves,
    FireBreath, SynthwaveWireframe, PrismaticShimmer, BreathingHeart,
    IceCrystals, Bioluminescence,
)

new_animations = [
    SunsetGradient, CloudsPassing, FloatingBalloons, NeonCyberpunk,
    AuroraBorealis, LavaLamp, StarryNight, MatrixRain, OceanWaves,
    FireBreath, SynthwaveWireframe, PrismaticShimmer, BreathingHeart,
    IceCrystals, Bioluminescence,
]

assert len(GENERAL_ANIMATIONS) >= 30, f'Expected >=30 animations, got {len(GENERAL_ANIMATIONS)}'
for cls in new_animations:
    assert cls in GENERAL_ANIMATIONS, f'{cls.__name__} not in GENERAL_ANIMATIONS'

print(f'GENERAL_ANIMATIONS count: {len(GENERAL_ANIMATIONS)} (OK)')
print('All 15 new animation classes registered: OK')
"
```

```bash
# Verify each new animation produces valid #RRGGBB hex output for frame 0
python -c "
import re
from unittest.mock import MagicMock
from teleclaude.cli.tui.animation_colors import ColorPalette
from teleclaude.cli.tui.animations.general import (
    SunsetGradient, CloudsPassing, FloatingBalloons, NeonCyberpunk,
    AuroraBorealis, LavaLamp, StarryNight, MatrixRain, OceanWaves,
    FireBreath, SynthwaveWireframe, PrismaticShimmer, BreathingHeart,
    IceCrystals, Bioluminescence,
)

HEX_RE = re.compile(r'^#[0-9a-f]{6}$', re.IGNORECASE)

palette = MagicMock(spec=ColorPalette)
palette.get.return_value = 'color(196)'
palette.__len__.return_value = 7

new_animations = [
    SunsetGradient, CloudsPassing, FloatingBalloons, NeonCyberpunk,
    AuroraBorealis, LavaLamp, StarryNight, MatrixRain, OceanWaves,
    FireBreath, SynthwaveWireframe, PrismaticShimmer, BreathingHeart,
    IceCrystals, Bioluminescence,
]

for cls in new_animations:
    anim = cls(palette, is_big=True, duration_seconds=5.0)
    result = anim.update(0)
    assert len(result) > 0, f'{cls.__name__} returned empty result'
    for pos, color in result.items():
        if color != -1:
            assert HEX_RE.match(str(color)), f'{cls.__name__} non-hex color at {pos}: {color!r}'
    print(f'{cls.__name__}: OK ({len(result)} pixels)')

print('All 15 animations produce valid HEX output: OK')
"
```
