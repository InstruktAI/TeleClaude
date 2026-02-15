"""Notifications 'Bell Sway' section animations — prototype.

4 Animation subclasses for config section states:
  - NotificationsIdle: Pendulum sway (highlight zone sways L-R-L)
  - NotificationsInteraction: Bell strike (center gold flash + ripple)
  - NotificationsSuccess: Chime cascade (musical scale L->R + alternating flash)
  - NotificationsError: Muted bell (rapid dim, red flash, settle)

All extend the Animation ABC. Use PixelMap for coordinates.
Return Dict[(x,y), int] from update() where int is curses pair ID.

Palette indices (via NotificationsPalette):
  0=subtle(23), 1=muted(37), 2=normal/cyan(51), 3=highlight/gold(220),
  4=accent/white(231), 5=accent_red(167)
"""

import math
from typing import Dict, Tuple

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_LETTERS,
    BIG_BANNER_WIDTH,
    LOGO_LETTERS,
    LOGO_WIDTH,
    PixelMap,
)


class NotificationsIdle(Animation):
    """Pendulum sway: 3-column bright zone sways L-R-L like a bell.

    A 3-column-wide zone of normal/cyan(2) oscillates across the banner
    against a muted(1) background. The pendulum has a ~40-frame cycle
    (20 frames each direction) at 200ms/frame = ~8 seconds per full swing.

    Speed: 200ms/frame. Loops indefinitely.
    """

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=200):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        # Cache column pixels for idle performance
        self._col_pixels: dict[int, list[Tuple[int, int]]] = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._center = self._width // 2

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        # Sine pendulum: ~40-frame cycle → angular speed = 2*pi/40 ≈ 0.157
        amplitude = self._width * 0.35  # sway covers ~70% of width
        pendulum_x = self._center + amplitude * math.sin(frame * 0.157)

        for col in range(self._width):
            dist = abs(col - pendulum_x)
            if dist < 1.5:
                color = self.palette.get(2)  # normal (cyan — bell center)
            elif dist < 3:
                color = self.palette.get(1)  # muted (bell edge)
            else:
                color = self.palette.get(0)  # subtle (background)

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result

    def is_complete(self, frame: int) -> bool:
        # Idle: never completes (looping in production)
        return False


class NotificationsInteraction(Animation):
    """Bell strike: center flashes gold, concentric ripple expands outward.

    Frame 0: Center 3 columns flash gold(3).
    Frames 1-8: Ripple of cyan(2) expands outward from center at 3 cols/frame.
    Beyond ripple: muted(1). After ripple passes: subtle(0).

    Creates concentric brightness rings, like a bell being struck.

    Speed: 80ms/frame. Duration ~1s.
    """

    def __init__(self, palette, is_big, duration_seconds=1.0, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels: dict[int, list[Tuple[int, int]]] = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._center = self._width // 2
        self._ripple_speed = 3  # columns per frame

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        ripple_radius = frame * self._ripple_speed

        for col in range(self._width):
            dist = abs(col - self._center)

            if frame == 0 and dist < 2:
                # Initial strike — gold flash at center
                color = self.palette.get(3)  # highlight (gold)
            elif abs(dist - ripple_radius) < 2:
                # Ripple front — cyan ring
                color = self.palette.get(2)  # normal (cyan)
            elif dist < ripple_radius:
                # Inside ripple — fading (already passed)
                color = self.palette.get(0)  # subtle
            else:
                # Outside ripple — waiting
                color = self.palette.get(1)  # muted

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result


class NotificationsSuccess(Animation):
    """Chime cascade: letters in ascending scale pattern, then alternating flash.

    Phase 1 (frames 0-9): Letters illuminate L->R, each at progressively
    brighter colors: subtle(0) → muted(1) → normal(2) → highlight(3).
    Like a musical scale ascending.
    Phase 2 (frames 10-15): All letters flash alternating cyan(2) and gold(3)
    — the chime resonating.
    Phase 3 (frames 16+): Settle to normal(2).

    Speed: 100ms/frame. Duration ~2s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        self._num_letters = len(self._letters)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._scale_end = self._num_letters
        self._chime_end = self._scale_end + 6

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._scale_end:
            # Phase 1: Scale ascent — letters light up with increasing brightness
            active_count = frame + 1
            for i in range(self._num_letters):
                if i < active_count:
                    # Brightness increases with letter position (0->3)
                    brightness = min(3, i * 3 // self._num_letters)
                    color = self.palette.get(brightness)
                else:
                    color = self.palette.get(0)  # subtle (not yet activated)
                for p in PixelMap.get_letter_pixels(self.is_big, i):
                    result[p] = color

        elif frame < self._chime_end:
            # Phase 2: Chime resonance — alternating cyan and gold
            chime_frame = frame - self._scale_end
            for i in range(self._num_letters):
                if (i + chime_frame) % 2 == 0:
                    color = self.palette.get(2)  # normal (cyan)
                else:
                    color = self.palette.get(3)  # highlight (gold)
                for p in PixelMap.get_letter_pixels(self.is_big, i):
                    result[p] = color

        else:
            # Phase 3: Settle to cyan
            for p in self._all_pixels:
                result[p] = self.palette.get(2)  # normal (cyan)

        return result


class NotificationsError(Animation):
    """Muted bell: rapid dim, single red flash, settle to muted.

    Frame 0: Still ringing — normal(2).
    Frame 1: Dimming — subtle(0).
    Frame 2: Red flash(5) — the bell is silenced.
    Frame 3+: Settle to muted(1).

    Short and sharp — the bell has been muted.

    Speed: 100ms/frame. Duration ~0.5s.
    """

    def __init__(self, palette, is_big, duration_seconds=0.8, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        if frame == 0:
            color = self.palette.get(2)  # normal (still ringing)
        elif frame == 1:
            color = self.palette.get(0)  # subtle (dimming)
        elif frame == 2:
            color = self.palette.get(5)  # accent_red (flash)
        else:
            color = self.palette.get(1)  # muted (settled)

        return {p: color for p in self._all_pixels}
