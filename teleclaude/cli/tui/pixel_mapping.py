"""Pixel mapping for TUI animations."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Legacy constants for backward compatibility/initialization
# Shifted +1 to the right for the Billboard margin (+1 left, +1 right)
BIG_BANNER_WIDTH = 84
BIG_BANNER_HEIGHT = 6
BIG_BANNER_LETTERS = [
    (1, 9),   # T
    (10, 17), # E
    (18, 25), # L
    (26, 33), # E
    (34, 41), # C
    (42, 49), # L
    (50, 57), # A
    (58, 66), # U
    (67, 74), # D
    (75, 82), # E
]

LOGO_WIDTH = 40
LOGO_HEIGHT = 3
LOGO_LETTERS = [
    (1, 3),   # T
    (5, 7),   # E
    (9, 11),  # L
    (13, 15), # E
    (17, 19), # C
    (21, 23), # L
    (25, 27), # A
    (29, 31), # U
    (33, 35), # D
    (37, 39), # E
]


@dataclass
class RenderTarget:
    """Definition of a render target area."""

    name: str
    width: int
    height: int
    letters: List[Tuple[int, int]]  # List of (start_x, end_x) tuples for each letter
    
    # Cached pixel lists
    _all_pixels: Optional[List[Tuple[int, int]]] = None
    _row_pixels: Dict[int, List[Tuple[int, int]]] = None
    _col_pixels: Dict[int, List[Tuple[int, int]]] = None

    def get_all_pixels(self) -> List[Tuple[int, int]]:
        if self._all_pixels is None:
            self._all_pixels = [(x, y) for y in range(self.height) for x in range(self.width)]
        return self._all_pixels

    def get_row_pixels(self, row_idx: int) -> List[Tuple[int, int]]:
        if self._row_pixels is None:
            self._row_pixels = {}
        if row_idx not in self._row_pixels:
            self._row_pixels[row_idx] = [(x, row_idx) for x in range(self.width)]
        return self._row_pixels[row_idx]

    def get_col_pixels(self, col_idx: int) -> List[Tuple[int, int]]:
        if self._col_pixels is None:
            self._col_pixels = {}
        if col_idx not in self._col_pixels:
            self._col_pixels[col_idx] = [(col_idx, y) for y in range(self.height)]
        return self._col_pixels[col_idx]


class TargetRegistry:
    """Registry for animation render targets."""

    def __init__(self):
        self._targets: Dict[str, RenderTarget] = {}
        # Register default targets
        self.register("banner", BIG_BANNER_WIDTH, BIG_BANNER_HEIGHT, BIG_BANNER_LETTERS)
        self.register("logo", LOGO_WIDTH, LOGO_HEIGHT, LOGO_LETTERS)

    def register(self, name: str, width: int, height: int, letters: Optional[List[Tuple[int, int]]] = None) -> None:
        """Register a new render target."""
        self._targets[name] = RenderTarget(name, width, height, letters or [])

    def get(self, name: str) -> Optional[RenderTarget]:
        return self._targets.get(name)


# Global registry instance
target_registry = TargetRegistry()


class PixelMap:
    """Helper for pixel-based calculations."""

    @staticmethod
    def _resolve_target(target_arg: bool | str) -> str:
        if isinstance(target_arg, bool):
            return "banner" if target_arg else "logo"
        return target_arg

    @staticmethod
    def get_is_letter(target_arg: bool | str, x: int, y: int) -> bool:
        """Check if a specific coordinate corresponds to a letter character."""
        target_name = PixelMap._resolve_target(target_arg)
        target = target_registry.get(target_name)
        if not target or not target.letters:
            return False
        return any(x >= start and x <= end for start, end in target.letters)

    @staticmethod
    def get_letter_pixels(
        target_arg: bool | str | None = None, letter_idx: int = 0, *, is_big: bool | None = None
    ) -> List[Tuple[int, int]]:
        """Get all (x, y) coordinates for a specific letter in the target."""
        if is_big is not None:
            target_name = "banner" if is_big else "logo"
        elif target_arg is not None:
            target_name = PixelMap._resolve_target(target_arg)
        else:
            return []

        target = target_registry.get(target_name)

        # No letters defined for this target
        if not target or not target.letters:
            return []

        if letter_idx < 0 or letter_idx >= len(target.letters):
            return []

        start_x, end_x = target.letters[letter_idx]
        pixels = []
        for y in range(target.height):
            for x in range(start_x, end_x + 1):
                pixels.append((x, y))
        return pixels

    @staticmethod
    def get_all_pixels(target_arg: bool | str | None = None, *, is_big: bool | None = None) -> List[Tuple[int, int]]:
        """Get all (x, y) coordinates for the entire grid of the target."""
        if is_big is not None:
            target_name = "banner" if is_big else "logo"
        elif target_arg is not None:
            target_name = PixelMap._resolve_target(target_arg)
        else:
            return []

        target = target_registry.get(target_name)
        if not target:
            return []

        return target.get_all_pixels()

    @staticmethod
    def get_row_pixels(
        target_arg: bool | str | None = None, row_idx: int = 0, *, is_big: bool | None = None
    ) -> List[Tuple[int, int]]:
        """Get all pixels in a specific row of the target."""
        if is_big is not None:
            target_name = "banner" if is_big else "logo"
        elif target_arg is not None:
            target_name = PixelMap._resolve_target(target_arg)
        else:
            return []

        target = target_registry.get(target_name)
        if not target:
            return []

        return target.get_row_pixels(row_idx)

    @staticmethod
    def get_column_pixels(
        target_arg: bool | str | None = None, col_idx: int = 0, *, is_big: bool | None = None
    ) -> List[Tuple[int, int]]:
        """Get all pixels in a specific column of the target."""
        if is_big is not None:
            target_name = "banner" if is_big else "logo"
        elif target_arg is not None:
            target_name = PixelMap._resolve_target(target_arg)
        else:
            return []

        target = target_registry.get(target_name)
        if not target:
            return []

        return target.get_col_pixels(col_idx)
