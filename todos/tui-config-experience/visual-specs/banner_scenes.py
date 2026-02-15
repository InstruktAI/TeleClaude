"""Banner scene animations — prototype.

Color-only effects that work within the existing Animation ABC.
These paint colors onto the existing TELECLAUDE banner text.

Scene categories:
  A. Color-only effects (4): PlasmaWave, RasterBars, Starfield, ShootingStar
  B. Character scenes (need SceneOverlay — described in banner_scenes.md)
  C. Banner transformations (5): BannerScrollOut, BannerDropIn, PixelDisintegrate,
     BannerGlitch, MarqueeWrap

This file contains Category A and Category C prototypes.
Category B (character scenes) requires SceneOverlay engine extension and is spec-only.

All animations use the SpectrumPalette (pair IDs 30-36) unless noted.
"""

import math
import random
from typing import Dict, List, Tuple

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

# ---------------------------------------------------------------------------
# Category A: Color-Only Banner Effects
# ---------------------------------------------------------------------------


class PlasmaWave(Animation):
    """A1: Classic C64 plasma effect — sinusoidal rainbow flowing across banner.

    Each column's color is determined by sin(frame * speed + col * phase_offset),
    mapped to the 7-color spectrum palette. Creates a continuously flowing,
    organic rainbow plasma. The signature party-mode animation.

    Speed: 80ms/frame. Loops indefinitely.
    """

    supports_small = True

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels: dict[int, list[Tuple[int, int]]] = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._palette_len = len(palette)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        for col in range(self._width):
            # Two overlapping sine waves for richer plasma
            t1 = math.sin(frame * 0.15 + col * 0.3)
            t2 = math.sin(frame * 0.1 + col * 0.12 + 2.0)
            combined = (t1 + t2) / 2.0  # -1..1

            # Map to palette index (0..palette_len-1)
            idx = int((combined + 1) / 2.0 * (self._palette_len - 1))
            idx = max(0, min(self._palette_len - 1, idx))
            color = self.palette.get(idx)

            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result

    def is_complete(self, frame: int) -> bool:
        return False


class RasterBars(Animation):
    """A2: C64 raster bar effect — bright horizontal band sweeps vertically.

    A 2-row-high bright band sweeps top->bottom through the banner.
    Band uses highlight colors, rest is dim. On each pass the band
    changes color, cycling through the spectrum.

    Speed: 120ms/frame. Loops indefinitely.
    """

    supports_small = False  # Needs 6 rows for full effect

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=120):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._height = BIG_BANNER_HEIGHT if is_big else LOGO_HEIGHT
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._palette_len = len(palette)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}
        # Band position sweeps top to bottom
        band_center = frame % self._height
        # Color changes each full sweep
        pass_color_idx = (frame // self._height) % self._palette_len
        band_color = self.palette.get(pass_color_idx)

        for x, y in self._all_pixels:
            dist = abs(y - band_center)
            if dist == 0:
                result[(x, y)] = band_color
            elif dist == 1:
                # Edge of band — slightly dimmer (previous palette color)
                dim_idx = (pass_color_idx - 1) % self._palette_len
                result[(x, y)] = self.palette.get(dim_idx)
            else:
                result[(x, y)] = -1  # Default (dim)

        return result

    def is_complete(self, frame: int) -> bool:
        return False


class Starfield(Animation):
    """A5: Starfield — sparse bright sparkles against dim banner.

    Most pixels stay dim (-1). 3-5 pixels per frame flash to white (last
    palette color) for 2 frames, then fade through intermediate colors
    back to dim. New sparkle positions every cycle. Like looking at the
    banner through a window into space.

    Speed: 150ms/frame. Loops indefinitely.
    """

    supports_small = True

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=150):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._palette_len = len(palette)
        # Track active stars: (pixel, birth_frame)
        self._stars: list[tuple[Tuple[int, int], int]] = []
        self._star_lifetime = 4  # frames a star lives

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        # Base: all dim
        result = {p: -1 for p in self._all_pixels}

        # Spawn new stars
        num_new = random.randint(2, 5)
        new_pixels = random.sample(self._all_pixels, min(num_new, len(self._all_pixels)))
        for p in new_pixels:
            self._stars.append((p, frame))

        # Render active stars with fade
        active = []
        for pixel, birth in self._stars:
            age = frame - birth
            if age < self._star_lifetime:
                active.append((pixel, birth))
                # Young stars bright, old stars dim
                if age == 0:
                    result[pixel] = self.palette.get(self._palette_len - 1)  # white
                elif age == 1:
                    result[pixel] = self.palette.get(self._palette_len - 2)
                elif age == 2:
                    result[pixel] = self.palette.get(self._palette_len - 3)
                # age == 3: fades to -1 (default)

        self._stars = active
        return result

    def is_complete(self, frame: int) -> bool:
        return False


class ShootingStar(Animation):
    """A4: Shooting star — bright streak across row 0, fading trail behind.

    A 4-pixel bright head streaks left-to-right along the top row (row 0 only).
    Behind it: a 6-pixel fading trail cycling through spectrum colors.
    Everything else remains -1 (default). Appears briefly, then banner is
    dark until the next trigger.

    Color-only, no character rendering needed. Row 0 only.

    Speed: 60ms/frame. Duration ~2s (single pass + fade).
    """

    supports_small = True

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=60):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._row0_cols: dict[int, list[Tuple[int, int]]] = {}
        for x, y in self._all_pixels:
            if y == 0:
                self._row0_cols.setdefault(x, []).append((x, y))
        self._palette_len = len(palette)
        self._head_len = 4
        self._trail_len = 6
        self._total_len = self._head_len + self._trail_len

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {p: -1 for p in self._all_pixels}

        head_x = frame * 2  # 2 cols per frame for speed

        for col in range(self._width):
            if col not in self._row0_cols:
                continue

            dist_behind = head_x - col
            if 0 <= dist_behind < self._head_len:
                # Bright head — last palette color (white/brightest)
                color = self.palette.get(self._palette_len - 1)
            elif self._head_len <= dist_behind < self._total_len:
                # Fading trail — cycle through spectrum, dimmer further back
                trail_pos = dist_behind - self._head_len
                color_idx = (frame + trail_pos) % self._palette_len
                color = self.palette.get(color_idx)
            else:
                continue

            for pixel in self._row0_cols[col]:
                result[pixel] = color

        return result


# ---------------------------------------------------------------------------
# Category C: Banner Transformation Animations
# ---------------------------------------------------------------------------


class BannerScrollOut(Animation):
    """C1: Banner colors slide left, creating scroll-out illusion.

    Columns go to -1 from left, one group at a time, as if the banner
    is sliding out of frame to the left. Then the new state slides in
    from the right.

    Use for tab transition effects.

    Speed: 80ms/frame. Duration ~1.5s.
    """

    supports_small = True

    def __init__(self, palette, is_big, duration_seconds=1.5, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._col_pixels: dict[int, list[Tuple[int, int]]] = {}
        for x, y in self._all_pixels:
            self._col_pixels.setdefault(x, []).append((x, y))
        # Slide out in ~half duration, slide back in second half
        self._slide_speed = max(1, self._width // 8)
        self._half_frames = self._width // self._slide_speed + 1
        self._palette_len = len(palette)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._half_frames:
            # Slide out: columns disappear left to right
            vanish_x = frame * self._slide_speed
            for col in range(self._width):
                if col <= vanish_x:
                    color = -1  # gone
                else:
                    # Still visible — cycling color
                    color = self.palette.get(col % self._palette_len)
                for pixel in self._col_pixels.get(col, []):
                    result[pixel] = color
        else:
            # Slide in: columns appear from right to left
            local_frame = frame - self._half_frames
            appear_x = self._width - 1 - (local_frame * self._slide_speed)
            for col in range(self._width):
                if col >= appear_x:
                    color = self.palette.get(col % self._palette_len)
                else:
                    color = -1  # not yet
                for pixel in self._col_pixels.get(col, []):
                    result[pixel] = color

        return result


class BannerDropIn(Animation):
    """C2: Banner rows appear top->bottom with bounce at the end.

    Rows become visible one at a time from top down. Each new row
    starts bright and fades. At the bottom: a bounce (last row
    disappears then reappears).

    Great for config tab entrance.

    Speed: 80ms/frame. Duration ~1.5s.
    """

    supports_small = False  # Needs 6 rows for bounce effect

    def __init__(self, palette, is_big, duration_seconds=1.5, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._height = BIG_BANNER_HEIGHT if is_big else LOGO_HEIGHT
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._palette_len = len(palette)
        # Drop: 2 frames per row, bounce: 4 frames
        self._drop_frames = self._height * 2
        self._bounce_start = self._drop_frames

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._drop_frames:
            # Drop phase: rows appear top-down
            visible_rows = (frame // 2) + 1
            newest_row = visible_rows - 1

            for x, y in self._all_pixels:
                if y < visible_rows:
                    if y == newest_row:
                        # Newest row — bright
                        color = self.palette.get(self._palette_len - 1)
                    else:
                        # Older rows — fade to normal
                        color = self.palette.get(self._palette_len // 2)
                    result[(x, y)] = color
                else:
                    result[(x, y)] = -1  # not yet visible

        elif frame < self._bounce_start + 4:
            # Bounce phase
            bounce_frame = frame - self._bounce_start
            if bounce_frame < 2:
                # Bounce up: hide last row
                for x, y in self._all_pixels:
                    if y < self._height - 1:
                        result[(x, y)] = self.palette.get(self._palette_len // 2)
                    else:
                        result[(x, y)] = -1
            else:
                # Settle: all visible
                for x, y in self._all_pixels:
                    result[(x, y)] = self.palette.get(self._palette_len // 2)
        else:
            # All settled
            color = self.palette.get(self._palette_len // 2)
            for p in self._all_pixels:
                result[p] = color

        return result


class PixelDisintegrate(Animation):
    """C3: Pixels randomly disappear then reassemble.

    Phase 1: Random pixels go to -1, edges first, center last.
    Phase 2: Brief pause (all dark).
    Phase 3: Reassemble — center first, edges last, in spectrum colors.

    The Thanos snap for TELECLAUDE.

    Speed: 80ms/frame. Duration ~4.5s.
    """

    supports_small = True

    def __init__(self, palette, is_big, duration_seconds=4.5, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._center_x = self._width // 2
        self._palette_len = len(palette)

        # Pre-sort pixels by distance from center (for edge-first disintegration)
        self._sorted_by_edge = sorted(
            self._all_pixels,
            key=lambda p: -abs(p[0] - self._center_x),  # edges first
        )
        # Reverse for center-first reassembly
        self._sorted_by_center = list(reversed(self._sorted_by_edge))

        self._total = len(self._all_pixels)
        # Phase timing
        self._disintegrate_frames = 20
        self._pause_frames = 5
        self._reassemble_frames = 20
        self._pause_start = self._disintegrate_frames
        self._reassemble_start = self._pause_start + self._pause_frames

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._disintegrate_frames:
            # Phase 1: Disintegrate — increasing % of pixels go dark
            progress = (frame + 1) / self._disintegrate_frames
            num_gone = int(progress * self._total)
            gone_set = set(tuple(p) for p in self._sorted_by_edge[:num_gone])

            # Remaining pixels get frantic colors (speed increases with progress)
            for p in self._all_pixels:
                if tuple(p) in gone_set:
                    result[p] = -1
                else:
                    # Frantic cycling
                    color_idx = (frame * 3 + p[0]) % self._palette_len
                    result[p] = self.palette.get(color_idx)

        elif frame < self._reassemble_start:
            # Phase 2: Pause — all dark
            for p in self._all_pixels:
                result[p] = -1

        else:
            # Phase 3: Reassemble — center first
            local_frame = frame - self._reassemble_start
            progress = min(1.0, (local_frame + 1) / self._reassemble_frames)
            num_visible = int(progress * self._total)

            visible_set = set(tuple(p) for p in self._sorted_by_center[:num_visible])

            for p in self._all_pixels:
                if tuple(p) in visible_set:
                    # Each appearing pixel starts bright, settles
                    # PERF: .index() is O(n) per pixel = O(n²) per frame.
                    # Phase 6 fix: pre-build {pixel: rank} dict in __init__.
                    age = num_visible - self._sorted_by_center.index(p)
                    if age < 3:
                        color = self.palette.get(self._palette_len - 1)
                    else:
                        color = self.palette.get(self._palette_len // 2)
                    result[p] = color
                else:
                    result[p] = -1

        return result


class BannerGlitch(Animation):
    """C4: VHS tracking error — random rows get wrong colors briefly.

    3-5 glitch bursts over 2 seconds. Each burst: 1-3 random rows shift
    to clashing colors for 1-2 frames, then snap back. Creates a digital
    corruption feel.

    Perfect for error states.

    Speed: 80ms/frame. Duration ~2s.
    """

    supports_small = True

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._height = BIG_BANNER_HEIGHT if is_big else LOGO_HEIGHT
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._palette_len = len(palette)
        # Pre-generate glitch timings (which frames have glitches)
        total_frames = int(duration_seconds * 1000 / speed_ms)
        self._glitch_frames: set[int] = set()
        for _ in range(random.randint(3, 5)):
            burst_start = random.randint(0, max(1, total_frames - 3))
            burst_len = random.randint(1, 2)
            for f in range(burst_start, burst_start + burst_len):
                self._glitch_frames.add(f)
        # Pre-generate which rows glitch at each frame
        self._glitch_rows: dict[int, set[int]] = {}
        for f in self._glitch_frames:
            num_rows = random.randint(1, 3)
            self._glitch_rows[f] = set(random.sample(range(self._height), min(num_rows, self._height)))

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame in self._glitch_frames:
            glitch_rows = self._glitch_rows.get(frame, set())
            for x, y in self._all_pixels:
                if y in glitch_rows:
                    # Glitched — random clashing color
                    color = self.palette.get(random.randint(0, self._palette_len - 1))
                else:
                    color = -1  # Normal
                result[(x, y)] = color
        else:
            # Normal — all default
            for p in self._all_pixels:
                result[p] = -1

        return result


class MarqueeWrap(Animation):
    """C5: Colors slide continuously left, wrapping around.

    Each column's color = spectrum[(frame + col) % spectrum_len].
    Creates the illusion of the banner on a rotating cylinder.
    Smooth, mesmerizing, continuous. Party mode background.

    Speed: 80ms/frame. Loops indefinitely.
    """

    supports_small = True

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=80):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        self._col_pixels: dict[int, list[Tuple[int, int]]] = {}
        for x, y in PixelMap.get_all_pixels(is_big):
            self._col_pixels.setdefault(x, []).append((x, y))
        self._palette_len = len(palette)

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        for col in range(self._width):
            idx = (frame + col) % self._palette_len
            color = self.palette.get(idx)
            for pixel in self._col_pixels.get(col, []):
                result[pixel] = color

        return result

    def is_complete(self, frame: int) -> bool:
        return False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BANNER_SCENE_ANIMATIONS = [
    # Category A: Color-Only
    PlasmaWave,
    RasterBars,
    Starfield,
    ShootingStar,
    # Category C: Transformations
    BannerScrollOut,
    BannerDropIn,
    PixelDisintegrate,
    BannerGlitch,
    MarqueeWrap,
]
