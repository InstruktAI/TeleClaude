"""Base classes for TUI animations."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_colors import ColorPalette

# Physical Z-Levels for occlusion
Z_SKY = 0
Z_BILLBOARD = 3
Z_TABS_INACTIVE = 5
Z_FOREGROUND = 7
Z_TABS_ACTIVE = 10


class Spectrum:
    """G1: Multi-stop HSV gradient engine for mud-free transitions."""

    def __init__(self, hex_colors: list[str]):
        from teleclaude.cli.tui.animation_colors import hex_to_rgb
        import colorsys
        self._hsv_stops = []
        for hc in hex_colors:
            try:
                r, g, b = hex_to_rgb(hc)
                self._hsv_stops.append(colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0))
            except:
                self._hsv_stops.append((0, 0, 0))

    def get_color(self, position: float) -> str:
        """Interpolate across the spectrum [0.0 to 1.0]."""
        from teleclaude.cli.tui.animation_colors import rgb_to_hex
        import colorsys
        
        pos = max(0.0, min(1.0, position))
        if not self._hsv_stops: return "#000000"
        if len(self._hsv_stops) == 1: return rgb_to_hex(*[int(x*255) for x in colorsys.hsv_to_rgb(*self._hsv_stops[0])])

        # Find the two stops to interpolate between
        scaled_pos = pos * (len(self._hsv_stops) - 1)
        idx = int(scaled_pos)
        next_idx = min(idx + 1, len(self._hsv_stops) - 1)
        factor = scaled_pos - idx

        if idx == next_idx:
            h, s, v = self._hsv_stops[idx]
        else:
            h1, s1, v1 = self._hsv_stops[idx]
            h2, s2, v2 = self._hsv_stops[next_idx]
            
            # Handle hue wraparound for shortest path
            if abs(h2 - h1) > 0.5:
                if h2 > h1: h1 += 1.0
                else: h2 += 1.0
            
            h = (h1 + (h2 - h1) * factor) % 1.0
            s = s1 + (s2 - s1) * factor
            v = v1 + (v2 - v1) * factor

        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return rgb_to_hex(int(r*255), int(g*255), int(b*255))


class RenderBuffer:
    """A collection of physical layers for Z-compositing."""
    def __init__(self) -> None:
        # Map Z-level to pixel dict
        self.layers: dict[int, dict[tuple[int, int], str | int]] = {}

    def add_pixel(self, z: int, x: int, y: int, value: str | int) -> None:
        if z not in self.layers: self.layers[z] = {}
        self.layers[z][(x, y)] = value


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
    def update(self, frame: int) -> dict[tuple[int, int], str | int] | RenderBuffer:
        """Calculate colors for the given frame."""

    def linear_surge(self, pos: float, active: float, width: float) -> float:
        """Calculate 1D intensity [0.0 to 1.0] for a volumetric surge."""
        dist = abs(pos - active)
        if dist >= width: return 0.0
        return 1.0 - (dist / width)

    def radial_field(self, x: int, y: int, cx: float, cy: float, radius: float) -> float:
        """Calculate 2D intensity [0.0 to 1.0] for a circular light source."""
        import math
        dist = math.sqrt((x - cx)**2 + (y - cy)**2)
        if dist >= radius: return 0.0
        return 1.0 - (dist / radius)

    def enforce_vibrancy(self, hex_color: str, sat: float = 0.95, val: float = 1.0) -> str:
        """Force high-vibrancy HSV state while preserving hue."""
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        import colorsys
        try:
            r, g, b = hex_to_rgb(hex_color)
            h, _, _ = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
            r, g, b = colorsys.hsv_to_rgb(h, sat, val)
            return rgb_to_hex(int(r*255), int(g*255), int(b*255))
        except: return hex_color

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
