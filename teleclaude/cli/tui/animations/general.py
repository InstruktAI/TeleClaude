"""General purpose rainbow animations."""

from __future__ import annotations

import math
import random

from teleclaude.cli.tui.animation_colors import MultiGradient, rgb_to_hex
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


class FullSpectrumCycle(Animation):
    """G1: All pixels synchronously cycle through the color palette."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        color_idx = frame % len(self.palette)
        color_pair = self.palette.get(color_idx)

        all_pixels = PixelMap.get_all_pixels(self.is_big)
        return {pixel: color_pair for pixel in all_pixels}


class LetterWaveLR(Animation):
    """G2: Each letter lights up sequentially from left to right."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        # One letter active at a time, cycling through palette
        active_letter_idx = frame % num_letters
        color_pair = self.palette.get(frame // num_letters)

        # To make it a "wave", we should probably clear other pixels or give them a base color.
        # But if we want it to be sparse, we just return the active part.

        # Let's try clearing all first for this specific animation to make it a distinct wave.
        # In a real wave, we might want a trail. For now, simple.

        # Redesigning Engine.update to optionally clear or overwrite.
        # For now, let's just return ALL pixels for this animation.
        return {
            p: (color_pair if i == active_letter_idx else -1)
            for i in range(num_letters)
            for p in PixelMap.get_letter_pixels(self.is_big, i)
        }


class LetterWaveRL(Animation):
    """G3: Each letter lights up sequentially from right to left."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = (num_letters - 1) - (frame % num_letters)
        color_pair = self.palette.get(frame // num_letters)

        result = {}
        for i in range(num_letters):
            letter_pixels = PixelMap.get_letter_pixels(self.is_big, i)
            if i == active_letter_idx:
                for p in letter_pixels:
                    result[p] = color_pair
            else:
                for p in letter_pixels:
                    result[p] = -1
        return result


class LineSweepTopBottom(Animation):
    """G6: Horizontal lines sweep from top to bottom."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        active_row = frame % height
        color_pair = self.palette.get(frame // height)

        result = {}
        for r in range(height):
            row_pixels = PixelMap.get_row_pixels(self.is_big, r)
            if r == active_row:
                for p in row_pixels:
                    result[p] = color_pair
            else:
                for p in row_pixels:
                    result[p] = -1
        return result


class LineSweepBottomTop(Animation):
    """G7: Horizontal lines sweep from bottom to top."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        active_row = (height - 1) - (frame % height)
        color_pair = self.palette.get(frame // height)

        result = {}
        for r in range(height):
            row_pixels = PixelMap.get_row_pixels(self.is_big, r)
            if r == active_row:
                for p in row_pixels:
                    result[p] = color_pair
            else:
                for p in row_pixels:
                    result[p] = -1
        return result


class MiddleOutVertical(Animation):
    """G8: Vertical center expansion (Big only)."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}  # Not supported for small logo

        height = BIG_BANNER_HEIGHT
        # For 6 lines, middle is between 2 and 3.
        # Steps: 0: (2,3), 1: (1,4), 2: (0,5)
        step = frame % 3
        active_rows = {2 - step, 3 + step}
        color_pair = self.palette.get(frame // 3)

        result = {}
        for r in range(height):
            row_pixels = PixelMap.get_row_pixels(self.is_big, r)
            if r in active_rows:
                for p in row_pixels:
                    result[p] = color_pair
            else:
                for p in row_pixels:
                    result[p] = -1
        return result


class WithinLetterSweepLR(Animation):
    """G4: Within each letter, pixels sweep horizontally left to right (Big only)."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}

        num_letters = len(BIG_BANNER_LETTERS)
        result = {}
        for i in range(num_letters):
            start_x, end_x = BIG_BANNER_LETTERS[i]
            letter_width = end_x - start_x + 1
            active_col_offset = frame % letter_width
            active_col = start_x + active_col_offset

            color_pair = self.palette.get(frame // letter_width)

            for x in range(start_x, end_x + 1):
                col_pixels = PixelMap.get_column_pixels(self.is_big, x)
                for p in col_pixels:
                    if x == active_col:
                        result[p] = color_pair
                    else:
                        result[p] = -1
        return result


class WithinLetterSweepRL(Animation):
    """G5: Within each letter, pixels sweep horizontally right to left (Big only)."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}

        num_letters = len(BIG_BANNER_LETTERS)
        result = {}
        for i in range(num_letters):
            start_x, end_x = BIG_BANNER_LETTERS[i]
            letter_width = end_x - start_x + 1
            active_col_offset = (letter_width - 1) - (frame % letter_width)
            active_col = start_x + active_col_offset

            color_pair = self.palette.get(frame // letter_width)

            for x in range(start_x, end_x + 1):
                col_pixels = PixelMap.get_column_pixels(self.is_big, x)
                for p in col_pixels:
                    if x == active_col:
                        result[p] = color_pair
                    else:
                        result[p] = -1
        return result


class RandomPixelSparkle(Animation):
    """G10: Random individual character pixels flash random colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        num_sparkles = len(all_pixels) // 10  # 10% of pixels sparkle

        result: dict[tuple[int, int], str | int] = {p: -1 for p in all_pixels}  # Clear all first

        sparkle_pixels = random.sample(all_pixels, num_sparkles)
        for p in sparkle_pixels:
            result[p] = self.palette.get(random.randint(0, len(self.palette) - 1))

        return result


class CheckerboardFlash(Animation):
    """G13: Alternating pixels flash in checkerboard pattern."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        color_pair = self.palette.get(frame // 2)
        # 0 or 1
        parity = frame % 2

        result = {}
        for x, y in all_pixels:
            if (x + y) % 2 == parity:
                result[(x, y)] = color_pair
            else:
                result[(x, y)] = -1
        return result


class WordSplitBlink(Animation):
    """G9: "TELE" vs "CLAUDE" blink alternately."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        split_x = 33 if self.is_big else 15

        color_pair = self.palette.get(frame // 2)
        parity = frame % 2

        result = {}
        for x, y in all_pixels:
            is_tele = x < split_x
            if (is_tele and parity == 0) or (not is_tele and parity == 1):
                result[(x, y)] = color_pair
            else:
                result[(x, y)] = -1
        return result


class DiagonalSweepDR(Animation):
    """G11: Pixels light up in diagonal waves top-left to bottom-right."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        max_val = BIG_BANNER_WIDTH + BIG_BANNER_HEIGHT
        active = frame % max_val
        color_pair = self.palette.get(frame // max_val)

        result = {}
        for x, y in PixelMap.get_all_pixels(True):
            if x + y == active:
                result[(x, y)] = color_pair
            else:
                result[(x, y)] = -1
        return result


class DiagonalSweepDL(Animation):
    """G12: Pixels light up in diagonal waves top-right to bottom-left."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        max_val = BIG_BANNER_WIDTH + BIG_BANNER_HEIGHT
        # Using x - y as diagonal invariant
        # range: -BIG_BANNER_HEIGHT to BIG_BANNER_WIDTH
        offset = BIG_BANNER_HEIGHT
        active = (frame % max_val) - offset
        color_pair = self.palette.get(frame // max_val)

        result = {}
        for x, y in PixelMap.get_all_pixels(True):
            if x - y == active:
                result[(x, y)] = color_pair
            else:
                result[(x, y)] = -1
        return result


class LetterShimmer(Animation):
    """G14: Each letter rapidly cycles through colors independently."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        result = {}
        for i in range(num_letters):
            # Each letter has its own random-ish phase
            color_idx = (frame + i * 3) % len(self.palette)
            color_pair = self.palette.get(color_idx)
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color_pair
        return result


class WavePulse(Animation):
    """G15: Color wave travels through word with trailing brightness gradient."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        active_x = frame % width

        result = {}
        for x in range(width):
            dist = abs(x - active_x)
            if dist == 0:
                color_pair = self.palette.get(frame // width)
            elif dist < 5:
                # Dimmer trailing effect (using palette indices if possible, or just -1)
                color_pair = self.palette.get((frame // width) - 1)
            else:
                color_pair = -1

            for p in PixelMap.get_column_pixels(self.is_big, x):
                result[p] = color_pair
        return result


# ---------------------------------------------------------------------------
# TrueColor (24-bit HEX) animation suite
# ---------------------------------------------------------------------------


class SunsetGradient(Animation):
    """TC1: Smooth sunset gradient sweeping left to right over time."""

    _grad = MultiGradient(["#FF4500", "#FFD700", "#FF00FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        shift = (frame * 2) % width
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            factor = ((x + shift) % width) / width
            result[(x, y)] = self._grad.get(factor)
        return result


class CloudsPassing(Animation):
    """TC2: Sky-blue background with fluffy white clouds drifting horizontally."""

    _SKY = "#87CEEB"
    _CLOUD = "#FFFFFF"
    _NUM_CLOUDS = 3

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result: dict[tuple[int, int], str | int] = {p: self._SKY for p in PixelMap.get_all_pixels(self.is_big)}
        for i in range(self._NUM_CLOUDS):
            speed = i + 1
            cx = (frame * speed + i * (width // self._NUM_CLOUDS)) % width
            cy = i % height
            for dx in range(-2, 3):
                nx = (cx + dx) % width
                result[(nx, cy)] = self._CLOUD
                if height > 1:
                    result[(nx, (cy + 1) % height)] = self._CLOUD
        return result


class FloatingBalloons(Animation):
    """TC3: Brightly colored clusters floating upward from the bottom."""

    _COLORS = ["#FF3366", "#FFD700", "#33CC66", "#FF3366", "#FFD700"]
    _NUM_BALLOONS = 5

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result: dict[tuple[int, int], str | int] = {p: -1 for p in PixelMap.get_all_pixels(self.is_big)}
        period = height + 4
        for i in range(self._NUM_BALLOONS):
            cx = (i * 13 + (frame // period) * 7) % width
            cy = (height - 1) - (frame % period)
            color = self._COLORS[i % len(self._COLORS)]
            for dx in range(-1, 2):
                for dy in range(-1, 1):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        result[(nx, ny)] = color
        return result


class NeonCyberpunk(Animation):
    """TC4: High-contrast cyan and magenta pulsing in diagonal waves."""

    _CYAN = "#00FFFF"
    _MAGENTA = "#FF00FF"
    _PERIOD = 8

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        half = self._PERIOD
        full = self._PERIOD * 2
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            diagonal = (x + y * 2 + frame * 2) % full
            result[(x, y)] = self._CYAN if diagonal < half else self._MAGENTA
        return result


class AuroraBorealis(Animation):
    """TC5: Wavy, organic vertical pulses of greens, blues, and purples."""

    _grad = MultiGradient(["#50C878", "#00008B", "#800080"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            wave = math.sin(x * 0.3 + frame * 0.2) * 0.3 + 0.5
            factor = (y / max(height - 1, 1) * 0.7 + wave * 0.3) % 1.0
            result[(x, y)] = self._grad.get(factor)
        return result


class LavaLamp(Animation):
    """TC6: Slow morphing blobs of red and orange rising and falling."""

    _grad = MultiGradient(["#FF4500", "#FF8C00", "#FF4500"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            blob = math.sin(x * 0.2 + frame * 0.1) * math.cos(y * 0.5 + frame * 0.07)
            factor = (blob + 1) / 2
            result[(x, y)] = self._grad.get(factor)
        return result


class StarryNight(Animation):
    """TC7: Midnight blue sky with randomly twinkling white and yellow stars."""

    _BG = "#0B1021"
    _STAR_WHITE = "#FFFFFF"
    _STAR_YELLOW = "#FFFACD"

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        result = {}
        for p in PixelMap.get_all_pixels(self.is_big):
            if random.random() < 0.05:
                result[p] = self._STAR_WHITE if random.random() < 0.7 else self._STAR_YELLOW
            else:
                result[p] = self._BG
        return result


class MatrixRain(Animation):
    """TC8: Neon green raindrop columns with fading trails falling downward."""

    _TRAIL = 4

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result: dict[tuple[int, int], str | int] = {p: "#000000" for p in PixelMap.get_all_pixels(self.is_big)}
        period = height + self._TRAIL
        for x in range(width):
            head_y = (frame + x * 3) % period
            for dy in range(self._TRAIL + 1):
                y = head_y - dy
                if 0 <= y < height:
                    if dy == 0:
                        result[(x, y)] = "#39FF14"
                    else:
                        factor = 1.0 - dy / self._TRAIL
                        g = int(0x64 * factor)
                        result[(x, y)] = rgb_to_hex(0, g, 0)
        return result


class OceanWaves(Animation):
    """TC9: Deep navy, teal and aqua sweeping in horizontal sine waves."""

    _grad = MultiGradient(["#000080", "#008080", "#00FFFF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            wave = math.sin(x * 0.3 - frame * 0.3) * 0.3 + 0.5
            factor = (y / max(height - 1, 1) * 0.5 + wave * 0.5) % 1.0
            result[(x, y)] = self._grad.get(factor)
        return result


class FireBreath(Animation):
    """TC10: Flickering fire heavy at the bottom, fading to ash near the top."""

    _hot = MultiGradient(["#FF0000", "#FF4500", "#FFD700"])
    _COOL = "#404040"

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            y_factor = y / max(height - 1, 1)
            intensity = y_factor + random.random() * 0.3
            if intensity < 0.35:
                result[(x, y)] = self._COOL
            else:
                color_factor = min(1.0, (intensity - 0.35) / 0.65)
                result[(x, y)] = self._hot.get(color_factor)
        return result


class SynthwaveWireframe(Animation):
    """TC11: Magenta horizon at bottom fading to dark purple sky at top."""

    _grad = MultiGradient(["#1A0533", "#6600CC", "#FF00FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            factor = y / max(height - 1, 1)
            result[(x, y)] = self._grad.get(factor)
        return result


class PrismaticShimmer(Animation):
    """TC12: Rapid, chaotic sparkling of bright jewel tones across all pixels."""

    _COLORS = ["#FF0000", "#0000FF", "#00FF00", "#FF00FF", "#00FFFF", "#FFD700", "#FF69B4", "#8A2BE2"]

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        result = {}
        for p in PixelMap.get_all_pixels(self.is_big):
            result[p] = random.choice(self._COLORS)
        return result


class BreathingHeart(Animation):
    """TC13: Crimson glow pulsing from the center outward like a heartbeat."""

    _grad = MultiGradient(["#8B0000", "#DC143C"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        cx, cy = width / 2, height / 2
        max_dist = math.sqrt(cx**2 + cy**2)
        pulse = (math.sin(frame * 0.3) + 1) / 2
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            norm_dist = dist / max_dist if max_dist > 0 else 0
            factor = max(0.0, min(1.0, 1.0 - norm_dist + (pulse - 0.5) * 0.4))
            result[(x, y)] = self._grad.get(factor)
        return result


class IceCrystals(Animation):
    """TC14: Frosty ice creeping inward from edges, turning everything white."""

    _grad = MultiGradient(["#87CEEB", "#E0FFFF", "#FFFFFF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        progress = frame / max(self.duration_frames - 1, 1)
        coverage = progress * 1.5
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            edge_x = min(x, width - 1 - x) / max(width / 2, 1)
            edge_y = min(y, height - 1 - y) / max(height / 2, 1)
            edge_dist = min(edge_x, edge_y)
            factor = max(0.0, min(1.0, coverage - edge_dist))
            result[(x, y)] = self._grad.get(factor)
        return result


class Bioluminescence(Animation):
    """TC15: Pitch-black sea with neon blue agents leaving glowing trails."""

    _NUM_AGENTS = 8
    _TRAIL_DECAY = 5

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        self._agents = [[random.randint(0, width - 1), random.randint(0, height - 1)] for _ in range(self._NUM_AGENTS)]
        self._trails: dict[tuple[int, int], int] = {}

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        # Move agents randomly
        for agent in self._agents:
            agent[0] = (agent[0] + random.choice([-1, 0, 1])) % width
            agent[1] = (agent[1] + random.choice([-1, 0, 1])) % height
        # Decay existing trails
        for pos in list(self._trails.keys()):
            self._trails[pos] -= 1
            if self._trails[pos] <= 0:
                del self._trails[pos]
        # Stamp agent positions into trails at full intensity
        for agent in self._agents:
            self._trails[(agent[0], agent[1])] = self._TRAIL_DECAY
        # Render
        result: dict[tuple[int, int], str | int] = {p: "#000000" for p in PixelMap.get_all_pixels(self.is_big)}
        for pos, intensity in self._trails.items():
            factor = intensity / self._TRAIL_DECAY
            r = int(0x46 * factor)
            g = int(0x82 * factor)
            b = int(0xB4 * factor)
            result[pos] = rgb_to_hex(r, g, b)
        return result


# Helper to provide some animations for random selection
GENERAL_ANIMATIONS = [
    FullSpectrumCycle,
    LetterWaveLR,
    LetterWaveRL,
    LineSweepTopBottom,
    LineSweepBottomTop,
    MiddleOutVertical,
    WithinLetterSweepLR,
    WithinLetterSweepRL,
    RandomPixelSparkle,
    CheckerboardFlash,
    WordSplitBlink,
    DiagonalSweepDR,
    DiagonalSweepDL,
    LetterShimmer,
    WavePulse,
    # TrueColor animations
    SunsetGradient,
    CloudsPassing,
    FloatingBalloons,
    NeonCyberpunk,
    AuroraBorealis,
    LavaLamp,
    StarryNight,
    MatrixRain,
    OceanWaves,
    FireBreath,
    SynthwaveWireframe,
    PrismaticShimmer,
    BreathingHeart,
    IceCrystals,
    Bioluminescence,
]
