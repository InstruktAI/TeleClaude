"""Telegram 'Blue Sky' section animations — prototype.

4 Animation subclasses for config section states:
  - TelegramIdle: Column breathing wave (continuous)
  - TelegramInteraction: Paper airplane swoosh
  - TelegramSuccess: Letter cascade with white pulse
  - TelegramError: Turbulence shake

All extend the Animation ABC. Use PixelMap for coordinates.
Return Dict[(x,y), int] from update() where int is curses pair ID.

Palette indices (via TelegramPalette):
  0=subtle(24), 1=muted(31), 2=normal(38), 3=highlight(117), 4=accent/white(231)
"""

import math
import random
from typing import Dict, Tuple

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_LETTERS,
    BIG_BANNER_WIDTH,
    LOGO_HEIGHT,
    LOGO_LETTERS,
    LOGO_WIDTH,
    PixelMap,
)


class TelegramIdle(Animation):
    """Column breathing: sine-wave shifts columns between muted and normal.

    A 3-pixel-wide wave of brightness travels L->R across the banner.
    Most pixels sit at muted (1), the wave lifts them to normal (2) with
    the peak hitting highlight (3). Smooth, alive, not distracting.

    Speed: 150ms/frame. Loops indefinitely.
    """

    # Production: looping=True in AnimationSlot (Phase 2)
    # Prototype: very high duration to simulate continuous
    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=150):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        # Cache column lookup for performance (idle runs forever)
        self._col_pixels: dict[int, list[Tuple[int, int]]] = {}
        for x, y in self._all_pixels:
            self._col_pixels.setdefault(x, []).append((x, y))

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        wave_speed = 0.12  # radians per frame — controls wave travel speed
        wave_width = 0.6  # radians per column — controls wave width (~3 cols)

        for col in range(self._width):
            # Sine wave: -1..1, phase-offset per column
            t = math.sin(frame * wave_speed - col * wave_width)

            # Map sine to palette: -1..0 = muted(1), 0..0.7 = normal(2), 0.7..1 = highlight(3)
            if t < 0:
                color = self.palette.get(1)  # muted
            elif t < 0.7:
                color = self.palette.get(2)  # normal
            else:
                color = self.palette.get(3)  # highlight (wave peak)

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result

    def is_complete(self, frame: int) -> bool:
        # Idle: never completes (looping in production)
        return False


class TelegramInteraction(Animation):
    """Paper airplane swoosh: bright streak zips L->R in 0.5s.

    A narrow streak of highlight(3)->accent(4)->highlight(3) moves across
    the banner. Behind it, pixels settle from normal(2) to muted(1) over
    4 frames, creating a fading wake.

    Speed: 100ms/frame, ~5 frames to cross = 0.5s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._col_pixels: dict[int, list[Tuple[int, int]]] = {}
        for x, y in self._all_pixels:
            self._col_pixels.setdefault(x, []).append((x, y))
        # Streak crosses entire width in ~5 frames
        self._streak_speed = max(1, self._width // 5)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        # Streak head position (moves fast)
        head_x = frame * self._streak_speed

        for col in range(self._width):
            dist = head_x - col  # positive = streak has passed this column

            if dist < 0:
                # Ahead of streak — untouched, subtle
                color = self.palette.get(0)  # subtle
            elif dist == 0:
                # Streak center — white flash
                color = self.palette.get(4)  # accent (white)
            elif dist <= 1:
                # Streak edge — highlight
                color = self.palette.get(3)  # highlight
            elif dist <= 3:
                # Near wake — normal, fading
                color = self.palette.get(2)  # normal
            elif dist <= 6:
                # Far wake — muted
                color = self.palette.get(1)  # muted
            else:
                # Settled — back to muted
                color = self.palette.get(1)  # muted

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result


class TelegramSuccess(Animation):
    """Letter cascade: letters light up L->R in highlight, pulse white, settle.

    Phase 1 (frames 0-19): Letters illuminate sequentially L->R, each at
    highlight(3), with 2-frame delay between letters. Unlit = subtle(0).
    Phase 2 (frame 20): ALL pixels flash white (accent 4).
    Phase 3 (frames 21-25): Settle to normal(2).

    Total ~2s at 100ms/frame = 20 frames.
    """

    def __init__(self, palette, is_big, duration_seconds=2.5, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        self._num_letters = len(self._letters)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        # Cascade phase: 2 frames per letter = 20 frames for 10 letters
        self._cascade_end = self._num_letters * 2
        # White flash frame
        self._flash_frame = self._cascade_end
        # Settle phase
        self._settle_start = self._flash_frame + 1

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._cascade_end:
            # Phase 1: Sequential letter cascade
            active_letter = frame // 2  # new letter every 2 frames
            for i in range(self._num_letters):
                letter_pixels = PixelMap.get_letter_pixels(self.is_big, i)
                if i <= active_letter:
                    # Lit — highlight
                    for p in letter_pixels:
                        result[p] = self.palette.get(3)  # highlight
                else:
                    # Not yet lit — subtle
                    for p in letter_pixels:
                        result[p] = self.palette.get(0)  # subtle

        elif frame == self._flash_frame:
            # Phase 2: White flash — all pixels accent
            for p in self._all_pixels:
                result[p] = self.palette.get(4)  # accent (white)

        else:
            # Phase 3: Settle to normal
            for p in self._all_pixels:
                result[p] = self.palette.get(2)  # normal

        return result


class TelegramError(Animation):
    """Turbulence shake: pixels alternate between normal and cold steel blue.

    3 rapid cycles of normal(2) <-> cold(palette index mapped to xterm 67).
    Since we don't have xterm 67 in the Telegram palette, we use subtle(0)
    as the "cold" contrast. 80ms speed for snappy shake.
    Settles to subtle(0) at the end.

    Note: For production, we could add xterm 67 (steel blue) as a 6th palette
    color. For prototype, subtle(24 deep blue) provides sufficient cold contrast
    against normal(38 sky blue).
    """

    def __init__(self, palette, is_big, duration_seconds=0.8, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        # 3 cycles × 2 frames per cycle = 6 shake frames, then settle
        self._shake_frames = 6

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._shake_frames:
            # Shake phase: alternate between normal and subtle (cold)
            if frame % 2 == 0:
                color = self.palette.get(2)  # normal (sky blue)
            else:
                color = self.palette.get(0)  # subtle (deep blue — reads as "cold")
            for p in self._all_pixels:
                result[p] = color
        else:
            # Settle to subtle
            for p in self._all_pixels:
                result[p] = self.palette.get(0)  # subtle

        return result
