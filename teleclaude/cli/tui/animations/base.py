"""Base classes for TUI animations."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_colors import ColorPalette


class Animation(ABC):
    """Abstract base class for all banner/logo animations."""

    # Class attribute: Override to False for big-only animations
    supports_small: bool = True
    # Theme filter: "dark", "light", or None (both)
    theme_filter: str | None = None

    def __init__(
        self,
        palette: ColorPalette,
        is_big: bool,
        duration_seconds: float,
        speed_ms: int = 100,
        target: str | None = None,
        dark_mode: bool = True,
        background_hex: str = "#000000",
        seed: int | None = None,
    ):
        """
        Args:
            palette: Color palette to use
            is_big: True for big banner, False for small logo
            duration_seconds: Total duration of the animation
            speed_ms: Milliseconds per frame
            target: Target render area name
            dark_mode: Current theme mode
            background_hex: Current terminal background color
            seed: Randomization seed for organic variety
        """
        self.palette = palette
        self.is_big = is_big
        self.duration_seconds = duration_seconds
        self.speed_ms = speed_ms
        self.duration_frames = int(duration_seconds * 1000 / speed_ms)
        self.target = target or ("banner" if is_big else "logo")
        self.dark_mode = dark_mode
        self.background_hex = background_hex
        self.seed = seed if seed is not None else random.randint(0, 1000000)
        self.rng = random.Random(self.seed)

    @abstractmethod
    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        """Calculate colors for the given frame."""

    def is_complete(self, frame: int) -> bool:
        """Check if animation has finished."""
        return frame >= self.duration_frames

    def get_modulation(self, frame: int) -> float:
        """Calculate an organic modulation value (0.3 -> 0.7 -> 0.5) for the frame."""
        progress = frame / max(1, self.duration_frames - 1)
        # Simple eased curve: starts slow, peaks, settles
        if progress < 0.2:
            return 0.3 + (progress / 0.2) * 0.4  # 0.3 -> 0.7
        elif progress < 0.6:
            return 0.7
        elif progress < 0.8:
            return 0.7 - ((progress - 0.6) / 0.2) * 0.2  # 0.7 -> 0.5
        else:
            return 0.5 - ((progress - 0.8) / 0.2) * 0.2  # 0.5 -> 0.3

    def get_contrast_safe_color(self, hex_color: str) -> str:
        """Ensure color is readable against the billboard background."""
        if not self.dark_mode:
            return hex_color  # Day mode on dark plate is safe

        # Night mode logic: boost brightness if too dark
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        try:
            r, g, b = hex_to_rgb(hex_color)
        except (ValueError, TypeError):
            return hex_color

        # If it's too dark (average RGB < 80), boost it to be vivid neon
        if (r + g + b) / 3 < 80:
            # Boost to at least 100 in each channel if it has some color,
            # or just a bright gray if it's black.
            return rgb_to_hex(max(r, 100), max(g, 100), max(b, 100))
        return hex_color
