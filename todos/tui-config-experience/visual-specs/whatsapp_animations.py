"""WhatsApp 'Message Bubble' section animations — prototype.

4 Animation subclasses for config section states:
  - WhatsAppIdle: Slow gradient loop (message composing feel)
  - WhatsAppInteraction: Message send bar sweep
  - WhatsAppSuccess: Double blue check (two sweeps in accent blue)
  - WhatsAppError: Gray pending clock (dim + slow sweep)

Palette indices (via WhatsAppPalette):
  0=subtle(23), 1=muted(30), 2=normal(36), 3=highlight(49), 4=accent/blue(75)
"""

import math
from typing import Dict, Tuple

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_WIDTH,
    LOGO_WIDTH,
    PixelMap,
)


class WhatsAppIdle(Animation):
    """Slow gradient loop: colors shift L->R simulating message composition.

    A gentle gradient travels left to right across the banner, colors
    shifting subtle->muted->normal->muted->subtle. Like watching someone
    type a message — something is happening, gently.

    Speed: 150ms/frame. Loops indefinitely.
    """

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=150):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        for col in range(self._width):
            # Traveling sine wave with wide wavelength
            t = math.sin(frame * 0.08 - col * 0.15)

            # Map to 3 palette levels
            if t < -0.3:
                color = self.palette.get(0)  # subtle
            elif t < 0.3:
                color = self.palette.get(1)  # muted
            else:
                color = self.palette.get(2)  # normal

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result

    def is_complete(self, frame: int) -> bool:
        return False


class WhatsAppInteraction(Animation):
    """Message send bar: bright green bar sweeps L->R like sending a message.

    A highlight(3) bar sweeps left to right. Behind it, columns settle to
    normal(2). Ahead, columns remain at muted(1). Like a progress bar for
    sending a message.

    Speed: 100ms/frame. Duration ~2s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._bar_speed = max(1, self._width // 8)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        bar_x = frame * self._bar_speed

        for col in range(self._width):
            dist = bar_x - col

            if dist < 0:
                color = self.palette.get(1)  # muted (unsent)
            elif dist <= 2:
                color = self.palette.get(3)  # highlight (sending edge)
            else:
                color = self.palette.get(2)  # normal (sent)

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result


class WhatsAppSuccess(Animation):
    """Double blue check: two quick sweeps in accent blue, then green settle.

    Phase 1 (frames 0-7): First blue sweep L->R (accent 4).
    Phase 2 (frames 8-15): Second blue sweep L->R (accent 4), slightly faster.
    Phase 3 (frames 16+): All pixels settle to highlight green (3).

    The two sweeps evoke WhatsApp's double checkmark for "read".

    Speed: 80ms/frame. Total ~1.6s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._sweep1_end = 8
        self._sweep2_end = 16
        self._sweep_speed = max(1, self._width // 7)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._sweep1_end:
            # First check sweep
            sweep_x = frame * self._sweep_speed
            for col in range(self._width):
                if col <= sweep_x and col >= sweep_x - 3:
                    color = self.palette.get(4)  # accent (blue)
                elif col < sweep_x - 3:
                    color = self.palette.get(2)  # normal (passed)
                else:
                    color = self.palette.get(1)  # muted (ahead)
                for pixel in self._col_pixels.get(col, []):
                    result[pixel] = color

        elif frame < self._sweep2_end:
            # Second check sweep (faster)
            local_frame = frame - self._sweep1_end
            sweep_x = local_frame * (self._sweep_speed + 2)
            for col in range(self._width):
                if col <= sweep_x and col >= sweep_x - 3:
                    color = self.palette.get(4)  # accent (blue)
                elif col < sweep_x - 3:
                    color = self.palette.get(3)  # highlight (confirmed)
                else:
                    color = self.palette.get(2)  # normal (first pass)
                for pixel in self._col_pixels.get(col, []):
                    result[pixel] = color
        else:
            # Settle to highlight green
            for p in self._all_pixels:
                result[p] = self.palette.get(3)  # highlight

        return result


class WhatsAppError(Animation):
    """Gray pending: dims to muted, slow clock-like sweep in subtle.

    Everything dims to muted(1). A single slow column of subtle(0) sweeps
    left to right — like a clock hand ticking, waiting for delivery.
    The "pending" state: your message hasn't been sent.

    Speed: 200ms/frame. Duration ~3s.
    """

    def __init__(self, palette, is_big, duration_seconds=3.0, speed_ms=200):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        # Slow sweep — 1 column per frame
        sweep_col = frame % self._width

        for col in range(self._width):
            if col == sweep_col:
                color = self.palette.get(0)  # subtle (the "clock hand")
            else:
                color = self.palette.get(1)  # muted (everything dim)

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result
