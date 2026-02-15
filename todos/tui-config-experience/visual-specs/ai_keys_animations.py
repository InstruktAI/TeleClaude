"""AI Keys 'Key Shimmer' section animations — prototype.

4 Animation subclasses for config section states:
  - AIKeysIdle: Gold sparkle (random pixel shimmer)
  - AIKeysInteraction: Key turn (vertical column sweep)
  - AIKeysSuccess: Vault opens (center-out expansion)
  - AIKeysError: Lock jams (rapid shake with red flash)

All extend the Animation ABC. Use PixelMap for coordinates.
Return Dict[(x,y), int] from update() where int is curses pair ID.

Palette indices (via AIKeysPalette):
  0=subtle(94), 1=muted(136), 2=normal/gold(178), 3=highlight(220),
  4=accent_white(231), 5=accent_red(88)
"""

import random
from typing import Dict, List, Tuple

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_WIDTH,
    LOGO_HEIGHT,
    LOGO_WIDTH,
    PixelMap,
)


class AIKeysIdle(Animation):
    """Gold sparkle: random 5% of pixels shimmer between gold and bright gold.

    Base state: all pixels at muted(1). Each frame, 5% of pixels randomly
    chosen sparkle — half at normal/gold(2), half at highlight/bright gold(3).
    Gives a living, glittering treasure effect.

    Speed: 200ms/frame. Loops indefinitely.
    """

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=200):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._num_sparkles = max(1, len(self._all_pixels) // 20)  # 5%

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        # Base: all muted
        result = {p: self.palette.get(1) for p in self._all_pixels}  # muted

        # Random sparkle selection
        sparkle_pixels = random.sample(self._all_pixels, self._num_sparkles)
        for i, p in enumerate(sparkle_pixels):
            # Alternate between gold(2) and bright gold(3) for variety
            if i % 2 == 0:
                result[p] = self.palette.get(2)  # normal (gold)
            else:
                result[p] = self.palette.get(3)  # highlight (bright gold)

        return result

    def is_complete(self, frame: int) -> bool:
        # Idle: never completes (looping in production)
        return False


class AIKeysInteraction(Animation):
    """Key turn: vertical column sweep L->R, each column flashes white then gold.

    A column of white (4) sweeps left to right. Behind it, columns settle
    to highlight (3). Ahead of it, columns remain at muted (1).
    Feels like a key turning in a lock — mechanical, precise, golden.

    Speed: 100ms/frame. Duration depends on banner width.
    """

    def __init__(self, palette, is_big, duration_seconds=3.0, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels: dict[int, List[Tuple[int, int]]] = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        # Sweep speed: 2 columns per frame
        self._sweep_speed = 2

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        sweep_x = frame * self._sweep_speed

        for col in range(self._width):
            dist = sweep_x - col

            if dist < 0:
                # Ahead of sweep — untouched
                color = self.palette.get(1)  # muted
            elif dist == 0:
                # Sweep front — white flash
                color = self.palette.get(4)  # accent (white)
            elif dist <= 2:
                # Just swept — bright gold
                color = self.palette.get(3)  # highlight
            else:
                # Settled — gold
                color = self.palette.get(2)  # normal (gold)

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result


class AIKeysSuccess(Animation):
    """Vault opens: center-out expansion with white flash.

    Phase 1: Two bright columns start at center, expand outward 2 cols/frame.
    Expanding edge is highlight(3), interior is normal(2), exterior is muted(1).
    Phase 2: When expansion reaches edges, single white(4) flash on all pixels.
    Phase 3: Settle into gold sparkle (all at highlight 3).

    Feels like a vault door swinging open to reveal treasure.
    """

    def __init__(self, palette, is_big, duration_seconds=3.0, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._center = self._width // 2
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._col_pixels: dict[int, List[Tuple[int, int]]] = {}
        for x, y in self._all_pixels:
            self._col_pixels.setdefault(x, []).append((x, y))
        # Expansion speed: 2 columns per frame from center
        self._expand_speed = 2
        # Frames to reach edge from center
        self._expand_frames = (self._center // self._expand_speed) + 1
        self._flash_frame = self._expand_frames

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._expand_frames:
            # Phase 1: Center-out expansion
            radius = frame * self._expand_speed

            for col in range(self._width):
                dist_from_center = abs(col - self._center)

                if dist_from_center <= radius:
                    # Inside the opened vault
                    if abs(dist_from_center - radius) <= 1:
                        # Expanding edge — bright gold
                        color = self.palette.get(3)  # highlight
                    else:
                        # Interior — gold
                        color = self.palette.get(2)  # normal
                else:
                    # Outside — still locked
                    color = self.palette.get(1)  # muted

                for pixel in self._col_pixels.get(col, []):
                    result[pixel] = color

        elif frame == self._flash_frame:
            # Phase 2: White flash
            for p in self._all_pixels:
                result[p] = self.palette.get(4)  # accent (white)

        else:
            # Phase 3: Settle to highlight (treasure revealed)
            for p in self._all_pixels:
                result[p] = self.palette.get(3)  # highlight

        return result


class AIKeysError(Animation):
    """Lock jams: 3 rapid L->R shakes with red flash.

    3 cycles of: all pixels flash dark red(5) for 1 frame, then snap back
    to muted(1) for 1 frame. The "shake" is the color alternation — reads
    as a jammed mechanism snapping back and forth.
    After 3 cycles, settle to muted(1).

    Speed: 80ms/frame for snappy feel. Total: ~0.5s.
    """

    def __init__(self, palette, is_big, duration_seconds=0.8, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        # 3 shake cycles × 2 frames = 6 frames, then settle
        self._shake_frames = 6

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._shake_frames:
            # Shake phase: alternate red and muted
            if frame % 2 == 0:
                color = self.palette.get(5)  # accent_red (dark red)
            else:
                color = self.palette.get(1)  # muted (khaki — snap back)
            for p in self._all_pixels:
                result[p] = color
        else:
            # Settle to muted
            for p in self._all_pixels:
                result[p] = self.palette.get(1)  # muted

        return result
