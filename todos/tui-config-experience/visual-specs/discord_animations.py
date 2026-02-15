"""Discord 'Blurple Pulse' section animations — prototype.

4 Animation subclasses for config section states:
  - DiscordIdle: LED underglow breathing (per-letter phase offset)
  - DiscordInteraction: Level-up flash (bottom-to-top brightness climb)
  - DiscordSuccess: GG celebration (rainbow burst, then blurple+lavender pose)
  - DiscordError: Disconnect (R->L dimming, red flash)

Palette indices (via DiscordPalette):
  0=subtle(55), 1=muted(62), 2=normal/blurple(63), 3=highlight(141),
  4=accent_lavender(189), 5=accent_red(203)
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


class DiscordIdle(Animation):
    """LED underglow: each letter breathes independently at offset rates.

    Each of the 10 letters cycles between subtle(0) and muted(1) with a
    sine-wave phase offset based on letter index. Creates organic shimmer
    like LED strips under a gaming rig — alive but non-distracting.

    Speed: 120ms/frame. Loops indefinitely.
    """

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=120):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        self._num_letters = len(self._letters)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        for i in range(self._num_letters):
            # Each letter has a unique phase offset
            phase = i * 0.7  # ~40 degrees apart
            t = math.sin(frame * 0.1 + phase)

            # Map sine to palette: -1..0 = subtle(0), 0..0.6 = muted(1), 0.6..1 = normal(2)
            if t < 0:
                color = self.palette.get(0)  # subtle
            elif t < 0.6:
                color = self.palette.get(1)  # muted
            else:
                color = self.palette.get(2)  # normal (blurple peak)

            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color

        return result

    def is_complete(self, frame: int) -> bool:
        return False


class DiscordInteraction(Animation):
    """Level-up flash: brightness climbs bottom->top row by row.

    Bottom row lights up first at muted(1), each successive row slightly
    brighter. When the top row reaches highlight(3), hold for 2 frames,
    then fade back down. Like a power bar filling from the bottom.

    Speed: 100ms/frame. Duration ~2s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._height = BIG_BANNER_HEIGHT if is_big else LOGO_HEIGHT
        self._all_pixels = PixelMap.get_all_pixels(is_big)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        # Phase 1: rows light up bottom->top (height frames)
        # Phase 2: hold (2 frames)
        # Phase 3: fade back to subtle
        active_row_from_bottom = frame  # 0 = bottom row

        for x, y in self._all_pixels:
            row_from_bottom = (self._height - 1) - y

            if row_from_bottom <= active_row_from_bottom:
                # This row is active — brightness proportional to position
                # Bottom rows dimmer, top rows brighter
                brightness = min(3, row_from_bottom)
                if active_row_from_bottom >= self._height:
                    # All rows filled — flash highlight
                    color = self.palette.get(3)  # highlight
                else:
                    color = self.palette.get(brightness)
            else:
                # Not yet reached — subtle
                color = self.palette.get(0)  # subtle

            result[(x, y)] = color

        return result


class DiscordSuccess(Animation):
    """GG celebration: rainbow burst then blurple+lavender victory pose.

    Phase 1 (frames 0-14): Rapid rainbow — all pixels cycle through a
    simulated spectrum using palette colors at high speed.
    Phase 2 (frames 15-25): Alternating letters in blurple(2) and lavender(4).
    Creates a victory podium feel.

    Speed: 100ms/frame. Total ~2.5s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.5, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        self._num_letters = len(self._letters)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._rainbow_end = 15
        # "Rainbow" using palette colors cycled rapidly
        self._rainbow_sequence = [0, 1, 2, 3, 2, 1]

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._rainbow_end:
            # Phase 1: Rainbow burst — all pixels cycle colors fast
            color_idx = self._rainbow_sequence[frame % len(self._rainbow_sequence)]
            color = self.palette.get(color_idx)
            for p in self._all_pixels:
                result[p] = color
        else:
            # Phase 2: Victory pose — alternating blurple and gold
            for i in range(self._num_letters):
                if i % 2 == 0:
                    color = self.palette.get(2)  # normal (blurple)
                else:
                    color = self.palette.get(4)  # accent_gold
                for p in PixelMap.get_letter_pixels(self.is_big, i):
                    result[p] = color

        return result


class DiscordError(Animation):
    """Disconnect: letters dim R->L, then flash red twice.

    Phase 1 (frames 0-9): Letters go dim one by one from right to left,
    each letter switching from muted(1) to subtle(0). Like connection
    dropping one node at a time.
    Phase 2 (frames 10-13): Two red(5) flashes with subtle(0) gaps.
    Phase 3: Settle to subtle(0).

    Speed: 80ms/frame. Total ~1.2s.
    """

    def __init__(self, palette, is_big, duration_seconds=1.5, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        self._num_letters = len(self._letters)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._dim_end = self._num_letters
        self._flash_start = self._dim_end

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._dim_end:
            # Phase 1: Letters dim R->L
            dim_count = frame + 1  # how many letters from right are dimmed
            for i in range(self._num_letters):
                from_right = (self._num_letters - 1) - i
                if from_right < dim_count:
                    color = self.palette.get(0)  # subtle (dimmed)
                else:
                    color = self.palette.get(1)  # muted (still connected)
                for p in PixelMap.get_letter_pixels(self.is_big, i):
                    result[p] = color

        elif frame < self._flash_start + 4:
            # Phase 2: Two red flashes
            flash_frame = frame - self._flash_start
            if flash_frame % 2 == 0:
                color = self.palette.get(5)  # accent_red
            else:
                color = self.palette.get(0)  # subtle (gap)
            for p in self._all_pixels:
                result[p] = color
        else:
            # Phase 3: Settle
            for p in self._all_pixels:
                result[p] = self.palette.get(0)  # subtle

        return result
