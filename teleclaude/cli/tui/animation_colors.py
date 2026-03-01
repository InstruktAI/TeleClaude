"""Color palette management for TUI animations.

Palettes return Rich-compatible color strings (e.g., "color(196)", "#ff5f5f")
that can be used directly in Rich Style objects for Textual rendering.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from teleclaude.cli.tui.theme import get_agent_color

# ---------------------------------------------------------------------------
# 24-bit TrueColor utilities
# ---------------------------------------------------------------------------


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert #RRGGBB hex string to (r, g, b) integer tuple."""
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert (r, g, b) integers to #RRGGBB string."""
    return f"#{r:02x}{g:02x}{b:02x}"


def interpolate_color(c1: str, c2: str, factor: float) -> str:
    """Linearly interpolate between two hex colors.

    Args:
        c1: Start color as #RRGGBB.
        c2: End color as #RRGGBB.
        factor: Blend factor in [0.0, 1.0]; 0.0 returns c1, 1.0 returns c2.

    Returns:
        Interpolated #RRGGBB string.
    """
    factor = max(0.0, min(1.0, factor))
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    return rgb_to_hex(
        int(r1 + (r2 - r1) * factor),
        int(g1 + (g2 - g1) * factor),
        int(b1 + (b2 - b1) * factor),
    )


class MultiGradient:
    """Multi-stop gradient returning interpolated hex colors for a 0.0–1.0 factor.

    Example::

        grad = MultiGradient(["#FF4500", "#FFD700", "#FF00FF"])
        color = grad.get(0.5)  # blend between orange and yellow
    """

    def __init__(self, stops: list[str]) -> None:
        if not stops:
            raise ValueError("MultiGradient requires at least one color stop.")
        self._stops = [hex_to_rgb(c) for c in stops]

    def get(self, factor: float) -> str:
        """Return interpolated #RRGGBB for *factor* in [0.0, 1.0]."""
        factor = max(0.0, min(1.0, factor))
        n = len(self._stops)
        if n == 1:
            return rgb_to_hex(*self._stops[0])
        seg = 1.0 / (n - 1)
        idx = min(int(factor / seg), n - 2)
        local = (factor - idx * seg) / seg
        r1, g1, b1 = self._stops[idx]
        r2, g2, b2 = self._stops[idx + 1]
        return rgb_to_hex(
            int(r1 + (r2 - r1) * local),
            int(g1 + (g2 - g1) * local),
            int(b1 + (b2 - b1) * local),
        )


# Spectrum: seven distinct colors that read well on both dark and light backgrounds.
# Converted to HEX to support contrast guard math.
_SPECTRUM_COLORS = (
    "#ff0000",  # Red
    "#ffff00",  # Yellow
    "#00ff00",  # Green
    "#00ffff",  # Cyan
    "#5fafff",  # Blue (lighter, visible on dark bg)
    "#ff00ff",  # Magenta
    "#ffffff",  # White
)


class ColorPalette(ABC):
    """Base class for animation color palettes."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def get(self, index: int) -> str:
        """Get a Rich color string for the given palette index."""

    @abstractmethod
    def __len__(self) -> int:
        """Number of colors in the palette."""


class SpectrumPalette(ColorPalette):
    """Rainbow spectrum palette."""

    def __init__(self) -> None:
        super().__init__("spectrum")

    def get(self, index: int) -> str:
        return _SPECTRUM_COLORS[index % len(_SPECTRUM_COLORS)]

    def __len__(self) -> int:
        return len(_SPECTRUM_COLORS)


class AgentPalette(ColorPalette):
    """Agent-specific palette (subtle, muted, normal — 3 brand colors only)."""

    def __init__(self, agent_name: str) -> None:
        super().__init__(f"agent_{agent_name}")
        self._colors = [
            get_agent_color(agent_name, "subtle"),
            get_agent_color(agent_name, "muted"),
            get_agent_color(agent_name, "normal"),
        ]

    def get(self, index: int) -> str:
        return self._colors[index % len(self._colors)]

    def __len__(self) -> int:
        return len(self._colors)


class SectionPalette(ColorPalette):
    """Section-specific palette using spectrum color subsets."""

    def __init__(self, section_name: str, color_indices: list[int]) -> None:
        super().__init__(section_name)
        self._colors = [_SPECTRUM_COLORS[i] for i in color_indices]

    def get(self, index: int) -> str:
        return self._colors[index % len(self._colors)]

    def __len__(self) -> int:
        return len(self._colors)


class PaletteRegistry:
    """Registry for available color palettes."""

    def __init__(self) -> None:
        self._palettes: dict[str, ColorPalette] = {}

    def register(self, palette: ColorPalette) -> None:
        self._palettes[palette.name] = palette

    def get(self, name: str) -> Optional[ColorPalette]:
        return self._palettes.get(name)


# Global registry
palette_registry = PaletteRegistry()
palette_registry.register(SpectrumPalette())
palette_registry.register(AgentPalette("claude"))
palette_registry.register(AgentPalette("gemini"))
palette_registry.register(AgentPalette("codex"))

# Section Palettes
# Indices: Red=0, Yellow=1, Green=2, Cyan=3, Blue=4, Magenta=5, White=6
palette_registry.register(SectionPalette("telegram", [4, 6]))  # Blue, White
palette_registry.register(SectionPalette("whatsapp", [2, 6]))  # Green, White
palette_registry.register(SectionPalette("discord", [4, 5, 6]))  # Blue, Magenta, White
palette_registry.register(SectionPalette("ai_keys", [2, 1]))  # Green, Yellow
palette_registry.register(SectionPalette("people", [6]))  # White
palette_registry.register(SectionPalette("notifications", [1, 6]))  # Yellow, White
palette_registry.register(SectionPalette("environment", [2, 3]))  # Green, Cyan
palette_registry.register(SectionPalette("validate", [2, 0]))  # Green, Red
