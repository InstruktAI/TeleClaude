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
    # If True, this animation is allowed to use colors darker than the letters
    is_shadow_caster: bool = False
    # If True, this color applies to the billboard background (reflection) as well
    is_external_light: bool = False

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
        """Calculate an organic modulation value (0.6 -> 1.0 -> 0.8) for the frame."""
        progress = frame / max(1, self.duration_frames - 1)
        # Higher floor (0.6) to ensure movement is always visible
        if progress < 0.2:
            return 0.6 + (progress / 0.2) * 0.4  # 0.6 -> 1.0
        elif progress < 0.6:
            return 1.0
        elif progress < 0.8:
            return 1.0 - ((progress - 0.6) / 0.2) * 0.2  # 1.0 -> 0.8
        else:
            return 0.8 - ((progress - 0.8) / 0.2) * 0.2  # 0.8 -> 0.6

    def get_electric_neon(self, hex_color: str) -> str:
        """Force a color into the high-vibrancy Electric Neon spectrum."""
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        import colorsys
        try:
            r, g, b = hex_to_rgb(hex_color)
            # Convert to HSV to enforce saturation and brightness
            h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
            # Enforce 95% saturation and 100% brightness for 'poppy' neon
            s = max(s, 0.95)
            v = 1.0
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            return rgb_to_hex(int(r*255), int(g*255), int(b*255))
        except (ValueError, TypeError, AttributeError):
            return hex_color

    def get_contrast_safe_color(self, hex_color: str) -> str:
        """Ensure color is readable against the billboard background."""
        if not self.dark_mode:
            return hex_color  # Day mode on dark plate is safe

        # Shadow casters are allowed to use dark colors for atmospheric effects
        if self.is_shadow_caster:
            return hex_color

        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        try:
            # Handle standard hex strings
            if hex_color.startswith("#"):
                r, g, b = hex_to_rgb(hex_color)
            else:
                # Fallback for unexpected formats (like color(N))
                return hex_color
        except (ValueError, TypeError, AttributeError):
            return hex_color

        # Floor: Animations should be strictly lighter than letters (#585858 / 88 RGB)
        # Use a threshold of 100 to ensure they pop.
        avg = (r + g + b) / 3
        if avg < 100:
            # Boost to at least 120 in each channel to ensure high-visibility neon
            return rgb_to_hex(max(r, 120), max(g, 120), max(b, 120))
        return hex_color
