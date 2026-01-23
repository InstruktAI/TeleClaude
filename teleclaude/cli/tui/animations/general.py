"""General purpose rainbow animations."""

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


class FullSpectrumCycle(Animation):
    """G1: All pixels synchronously cycle through the color palette."""

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        color_idx = frame % len(self.palette)
        color_pair = self.palette.get(color_idx)

        all_pixels = PixelMap.get_all_pixels(self.is_big)
        return {pixel: color_pair for pixel in all_pixels}


class LetterWaveLR(Animation):
    """G2: Each letter lights up sequentially from left to right."""

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        num_sparkles = len(all_pixels) // 10  # 10% of pixels sparkle

        result = {p: -1 for p in all_pixels}  # Clear all first

        sparkle_pixels = random.sample(all_pixels, num_sparkles)
        for p in sparkle_pixels:
            result[p] = self.palette.get(random.randint(0, len(self.palette) - 1))

        return result


class CheckerboardFlash(Animation):
    """G13: Alternating pixels flash in checkerboard pattern."""

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
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
]
