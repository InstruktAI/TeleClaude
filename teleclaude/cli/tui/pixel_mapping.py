"""Pixel mapping for TUI animations."""

from typing import List, Tuple

# Big Banner Letter Boundaries (inclusive)
# Grid: 82x6
BIG_BANNER_WIDTH = 82
BIG_BANNER_HEIGHT = 6
BIG_BANNER_LETTERS = [
    (0, 8),  # T
    (9, 16),  # E
    (17, 24),  # L
    (25, 32),  # E
    (33, 40),  # C
    (41, 48),  # L
    (49, 56),  # A
    (57, 65),  # U
    (66, 73),  # D
    (74, 81),  # E
]

# Small Logo Letter Boundaries (inclusive)
# Grid: 39x3
LOGO_WIDTH = 39
LOGO_HEIGHT = 3
LOGO_LETTERS = [
    (0, 2),  # T
    (4, 6),  # E
    (8, 10),  # L
    (12, 14),  # E
    (16, 18),  # C
    (20, 22),  # L
    (24, 26),  # A
    (28, 30),  # U
    (32, 34),  # D
    (36, 38),  # E
]


class PixelMap:
    """Helper for pixel-based calculations."""

    @staticmethod
    def get_letter_pixels(is_big: bool, letter_idx: int) -> List[Tuple[int, int]]:
        """Get all (x, y) coordinates for a specific letter."""
        boundaries = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        height = BIG_BANNER_HEIGHT if is_big else LOGO_HEIGHT

        if letter_idx < 0 or letter_idx >= len(boundaries):
            return []

        start_x, end_x = boundaries[letter_idx]
        pixels = []
        for y in range(height):
            for x in range(start_x, end_x + 1):
                pixels.append((x, y))
        return pixels

    @staticmethod
    def get_all_pixels(is_big: bool) -> List[Tuple[int, int]]:
        """Get all (x, y) coordinates for the entire grid."""
        width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if is_big else LOGO_HEIGHT

        pixels = []
        for y in range(height):
            for x in range(width):
                pixels.append((x, y))
        return pixels

    @staticmethod
    def get_row_pixels(is_big: bool, row_idx: int) -> List[Tuple[int, int]]:
        """Get all pixels in a specific row."""
        width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if is_big else LOGO_HEIGHT

        if row_idx < 0 or row_idx >= height:
            return []

        return [(x, row_idx) for x in range(width)]

    @staticmethod
    def get_column_pixels(is_big: bool, col_idx: int) -> List[Tuple[int, int]]:
        """Get all pixels in a specific column."""
        width = BIG_BANNER_WIDTH if is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if is_big else LOGO_HEIGHT

        if col_idx < 0 or col_idx >= width:
            return []

        return [(col_idx, y) for y in range(height)]
