"""Validate 'The Scan' section animations — prototype.

4 Animation subclasses for config section states:
  - ValidateIdle: Scanning beam (column sweeps through spectrum colors)
  - ValidateInteraction: Pulse quicken (same beam at 2x speed)
  - ValidateSuccess: FIREWORKS (6-second multi-stage celebration!)
  - ValidateError: Warning pulse (red/gold alternation, then fade)

All extend the Animation ABC. Use PixelMap for coordinates.
Return Dict[(x,y), int] from update() where int is curses pair ID.

Palette indices (via ValidatePalette):
  0=success_green(46), 1=failure_red(196), 2=settle_gold(220)

This animation also uses SpectrumPalette (pairs 30-36) directly for the
scanning beam rainbow effect. The validate palette is only for state colors.
"""

import random
from typing import Dict, List, Tuple

from teleclaude.cli.tui.animation_colors import palette_registry
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_WIDTH,
    LOGO_WIDTH,
    PixelMap,
)


class ValidateIdle(Animation):
    """Scanning beam: single bright column sweeps L->R in spectrum colors.

    A one-column-wide beam sweeps left to right, cycling through the
    7 spectrum colors. Rest of the banner at dim (-1 = default rendering).
    Like a barcode scanner — clinical, methodical.

    Speed: 100ms/frame. Loops indefinitely.
    """

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        # Cache column pixels for idle performance
        self._col_pixels: dict[int, List[Tuple[int, int]]] = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._spectrum = palette_registry.get("spectrum")

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        beam_x = frame % self._width
        # Cycle through spectrum colors with each full sweep
        color_idx = (frame // self._width) % 7

        for col in range(self._width):
            if col == beam_x:
                # Beam — bright spectrum color
                color = self._spectrum.get(color_idx)
            elif abs(col - beam_x) <= 1:
                # Beam glow — adjacent spectrum color
                color = self._spectrum.get((color_idx + 1) % 7)
            else:
                # Background — revert to default rendering
                color = -1

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result

    def is_complete(self, frame: int) -> bool:
        # Idle: never completes (looping in production)
        return False


class ValidateInteraction(Animation):
    """Pulse quicken: same scanning beam but at 2x speed (2 cols/frame).

    Identical to ValidateIdle but the beam moves faster — the scan is
    intensifying as the user interacts with validation controls.

    Speed: 100ms/frame, but beam advances 2 columns per frame.
    """

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels: dict[int, List[Tuple[int, int]]] = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._spectrum = palette_registry.get("spectrum")
        self._beam_speed = 2  # 2x normal speed

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        beam_x = (frame * self._beam_speed) % self._width
        color_idx = ((frame * self._beam_speed) // self._width) % 7

        for col in range(self._width):
            if col == beam_x:
                color = self._spectrum.get(color_idx)
            elif abs(col - beam_x) <= 1:
                color = self._spectrum.get((color_idx + 1) % 7)
            else:
                color = -1

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result

    def is_complete(self, frame: int) -> bool:
        return False


class ValidateSuccess(Animation):
    """FIREWORKS: 6-second multi-stage celebration. The grand finale.

    Phase 1 (frames 0-10): Green(success) expansion from center outward.
    Phase 2 (frames 11-30): Random pixel clusters (5-8 pixels) in spectrum
      colors at random positions, each persisting 3 frames. Firework bursts.
    Phase 3 (frames 31-50): Cascading rainbow sweep L->R at 3x speed.
    Phase 4 (frames 51-60): Settle to gold(settle) with gentle sparkle.

    Speed: 100ms/frame. Duration: 6 seconds. This is the BIG payoff.
    """

    def __init__(self, palette, is_big, duration_seconds=6.0, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._col_pixels: dict[int, List[Tuple[int, int]]] = {}
        for x, y in self._all_pixels:
            self._col_pixels.setdefault(x, []).append((x, y))
        self._center = self._width // 2
        self._spectrum = palette_registry.get("spectrum")
        # Pre-generate firework burst positions for frame consistency
        self._bursts: list[tuple[list[Tuple[int, int]], int, int]] = []
        for i in range(8):  # 8 bursts across the fireworks phase
            burst_size = random.randint(5, 8)
            burst_pixels = random.sample(self._all_pixels, burst_size)
            burst_color_idx = i % 7  # cycle through spectrum
            burst_start_frame = 11 + i * 2  # staggered: frame 11, 13, 15...
            self._bursts.append((burst_pixels, burst_color_idx, burst_start_frame))

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame <= 10:
            # Phase 1: Green expansion from center
            radius = frame * (self._width // 20)  # expand to edges by frame 10
            for col in range(self._width):
                dist = abs(col - self._center)
                if dist <= radius:
                    color = self.palette.get(0)  # success (green)
                else:
                    color = -1  # default
                for pixel in self._col_pixels.get(col, []):
                    result[pixel] = color

        elif frame <= 30:
            # Phase 2: Firework bursts on green background
            result = {p: self.palette.get(0) for p in self._all_pixels}  # success base
            # Active bursts (each persists 3 frames)
            for burst_pixels, color_idx, start_frame in self._bursts:
                if start_frame <= frame < start_frame + 3:
                    color = self._spectrum.get(color_idx)
                    for p in burst_pixels:
                        result[p] = color

        elif frame <= 50:
            # Phase 3: Cascading rainbow sweep L->R at 3x speed
            sweep_x = (frame - 31) * 3  # 3 columns per frame
            for col in range(self._width):
                if col <= sweep_x:
                    # Swept — spectrum color based on column position
                    color = self._spectrum.get(col % 7)
                else:
                    color = -1  # not yet swept
                for pixel in self._col_pixels.get(col, []):
                    result[pixel] = color

        else:
            # Phase 4: Settle to gold with gentle spectrum sparkle
            num_sparkles = len(self._all_pixels) // 15
            sparkle_set = set(random.sample(range(len(self._all_pixels)), num_sparkles))
            for idx, p in enumerate(self._all_pixels):
                if idx in sparkle_set:
                    result[p] = self._spectrum.get(random.randint(0, 6))  # spectrum sparkle
                else:
                    result[p] = self.palette.get(2)  # settle (gold)

        return result


class ValidateError(Animation):
    """Warning pulse: alternating red/gold pulse, then fade.

    4 cycles of failure_red(1) and settle_gold(2) alternation at 100ms.
    Then hold red for 2 frames, then revert to default.

    Speed: 100ms/frame. Duration ~1.2s.
    """

    def __init__(self, palette, is_big, duration_seconds=1.2, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._pulse_frames = 8  # 4 cycles x 2 frames

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._pulse_frames:
            # Alternating red/gold pulse
            if frame % 2 == 0:
                color = self.palette.get(1)  # failure (red)
            else:
                color = self.palette.get(2)  # settle (gold)
            for p in self._all_pixels:
                result[p] = color

        elif frame < self._pulse_frames + 2:
            # Fade: red holding
            for p in self._all_pixels:
                result[p] = self.palette.get(1)  # failure (red)

        else:
            # Settled: revert to default
            for p in self._all_pixels:
                result[p] = -1

        return result
