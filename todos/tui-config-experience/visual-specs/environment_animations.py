"""Environment 'Matrix Rain' section animations — prototype.

4 Animation subclasses for config section states:
  - EnvironmentIdle: Matrix sparkle (random green pixel rain)
  - EnvironmentInteraction: Cursor scan (bright bar sweeps L->R)
  - EnvironmentSuccess: System ready (progress bar fill + white flash)
  - EnvironmentError: Segfault (escalating red corruption, crash, recovery)

All extend the Animation ABC. Use PixelMap for coordinates.
Return Dict[(x,y), int] from update() where int is curses pair ID.

Palette indices (via EnvironmentPalette):
  0=subtle(22), 1=muted(28), 2=normal(34), 3=highlight/neon(46),
  4=accent_red(196), 5=accent_white(231)
"""

import random
from typing import Dict, List, Tuple

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_WIDTH,
    LOGO_WIDTH,
    PixelMap,
)


class EnvironmentIdle(Animation):
    """Matrix sparkle: random 8% of pixels flash green each frame.

    Most pixels at subtle(0). Each frame, ~8% randomly chosen get either
    normal(2) or highlight(3) — like digital rain characters briefly
    illuminating before fading back into the dark.

    Speed: 100ms/frame. Loops indefinitely.
    """

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._num_sparkles = max(1, len(self._all_pixels) * 8 // 100)  # 8%

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        # Base: all subtle (the dark)
        result = {p: self.palette.get(0) for p in self._all_pixels}  # subtle

        # Random sparkle selection — new set each frame
        sparkle_pixels = random.sample(self._all_pixels, self._num_sparkles)
        for i, p in enumerate(sparkle_pixels):
            # Mix of standard green and bright neon
            if i % 3 == 0:
                result[p] = self.palette.get(3)  # highlight (neon — bright rain)
            else:
                result[p] = self.palette.get(2)  # normal (standard rain)

        return result

    def is_complete(self, frame: int) -> bool:
        # Idle: never completes (looping in production)
        return False


class EnvironmentInteraction(Animation):
    """Cursor scan: bright vertical bar sweeps L->R like a scanning cursor.

    Highlight(3) bar moves left to right. Behind it: normal(2).
    Ahead: subtle(0). Like a cursor scanning environment variables.

    Speed: 80ms/frame. Duration ~2s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels: dict[int, List[Tuple[int, int]]] = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._scan_speed = 2  # columns per frame

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        scan_x = frame * self._scan_speed

        for col in range(self._width):
            dist = scan_x - col

            if dist < 0:
                color = self.palette.get(0)  # subtle (not scanned yet)
            elif dist == 0:
                color = self.palette.get(3)  # highlight (cursor — bright neon)
            elif dist <= 1:
                color = self.palette.get(3)  # highlight (cursor glow)
            else:
                color = self.palette.get(2)  # normal (scanned — green)

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result


class EnvironmentSuccess(Animation):
    """System ready: columns fill L->R like a progress bar, then flash.

    Phase 1: Columns illuminate left to right at highlight(3), 2 cols/frame.
    Like a progress bar filling to 100%.
    Phase 2 (flash frame): All pixels flash white(5).
    Phase 3: Settle to normal(2).

    Speed: 60ms/frame (fast progress). Duration ~2s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=60):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._col_pixels: dict[int, List[Tuple[int, int]]] = {}
        for x, y in self._all_pixels:
            self._col_pixels.setdefault(x, []).append((x, y))
        self._fill_speed = 2  # columns per frame
        self._fill_end = self._width // self._fill_speed + 1
        self._flash_frame = self._fill_end

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._fill_end:
            # Phase 1: Progress bar filling
            filled_to = frame * self._fill_speed
            for col in range(self._width):
                if col <= filled_to:
                    color = self.palette.get(3)  # highlight (filled — neon)
                else:
                    color = self.palette.get(1)  # muted (empty)
                for pixel in self._col_pixels.get(col, []):
                    result[pixel] = color

        elif frame == self._flash_frame:
            # Phase 2: White flash
            for p in self._all_pixels:
                result[p] = self.palette.get(5)  # accent_white

        else:
            # Phase 3: Settle to normal green
            for p in self._all_pixels:
                result[p] = self.palette.get(2)  # normal

        return result


class EnvironmentError(Animation):
    """Segfault: escalating red corruption, crash, recovery.

    Frames 0-2: Random pixels flash red(4), increasing density.
      Frame 0: 5% red. Frame 1: 15% red. Frame 2: 30% red.
    Frames 3-4: Everything goes to subtle(0) — the crash.
    Frame 5+: Settle to muted(1) — recovery.

    Speed: 100ms/frame. Duration ~0.8s.
    """

    def __init__(self, palette, is_big, duration_seconds=0.8, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._total = len(self._all_pixels)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame <= 2:
            # Escalating red corruption
            pct = [5, 15, 30][frame]
            num_red = max(1, self._total * pct // 100)
            red_set = set(random.sample(range(self._total), num_red))
            for idx, p in enumerate(self._all_pixels):
                if idx in red_set:
                    result[p] = self.palette.get(4)  # accent_red (corruption)
                else:
                    result[p] = self.palette.get(1)  # muted (still alive)

        elif frame <= 4:
            # Crash — everything dims
            for p in self._all_pixels:
                result[p] = self.palette.get(0)  # subtle (darkness)

        else:
            # Recovery
            for p in self._all_pixels:
                result[p] = self.palette.get(1)  # muted

        return result
