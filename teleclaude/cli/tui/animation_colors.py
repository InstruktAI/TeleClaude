"""Color palette management for TUI animations."""

import curses
from abc import ABC, abstractmethod
from typing import Dict, Optional

from teleclaude.cli.tui.theme import AGENT_COLORS


class ColorPalette(ABC):
    """Base class for animation color palettes."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def get(self, index: int) -> int:
        """Get curses color pair ID for the given palette index."""
        pass

    @abstractmethod
    def __len__(self) -> int:
        """Number of colors in the palette."""
        pass


class SpectrumPalette(ColorPalette):
    """Rainbow spectrum palette using standard curses colors."""

    def __init__(self):
        super().__init__("spectrum")
        # Pair IDs 30-36 for spectrum (Red, Yellow, Green, Cyan, Blue, Magenta, White)
        self.color_pairs = list(range(30, 37))

    def get(self, index: int) -> int:
        return self.color_pairs[index % len(self.color_pairs)]

    def __len__(self) -> int:
        return len(self.color_pairs)


class AgentPalette(ColorPalette):
    """Agent-specific palette (Muted, Normal, Highlight)."""

    def __init__(self, agent_name: str):
        super().__init__(f"agent_{agent_name}")
        agent_cfg = AGENT_COLORS.get(agent_name, AGENT_COLORS["claude"])
        self.color_pairs = [
            agent_cfg["subtle"],
            agent_cfg["muted"],
            agent_cfg["normal"],
            agent_cfg["highlight"],
        ]

    def get(self, index: int) -> int:
        return self.color_pairs[index % len(self.color_pairs)]

    def __len__(self) -> int:
        return len(self.color_pairs)


class SectionPalette(ColorPalette):
    """Section-specific palette using spectrum color pairs."""

    def __init__(self, section_name: str, color_indices: list[int]):
        super().__init__(section_name)
        # Map 0-6 indices to spectrum pairs 30-36
        # Red=0(30), Yellow=1(31), Green=2(32), Cyan=3(33), Blue=4(34), Magenta=5(35), White=6(36)
        self.color_pairs = [30 + i for i in color_indices]

    def get(self, index: int) -> int:
        return self.color_pairs[index % len(self.color_pairs)]

    def __len__(self) -> int:
        return len(self.color_pairs)


class PaletteRegistry:
    """Registry for available color palettes."""

    def __init__(self):
        self._palettes: Dict[str, ColorPalette] = {}
        self._initialized = False

    def register(self, palette: ColorPalette) -> None:
        self._palettes[palette.name] = palette

    def get(self, name: str) -> Optional[ColorPalette]:
        return self._palettes.get(name)

    def initialize_colors(self) -> None:
        """Initialize curses color pairs for the spectrum palette.

        This should be called after curses.start_color().
        """
        if self._initialized:
            return

        # Initialize Spectrum pairs (30-36)
        # Red, Yellow, Green, Cyan, Blue, Magenta, White
        # Colors: 1, 3, 2, 6, 4, 5, 7 (standard curses color IDs)
        colors = [
            curses.COLOR_RED,
            curses.COLOR_YELLOW,
            curses.COLOR_GREEN,
            curses.COLOR_CYAN,
            curses.COLOR_BLUE,
            curses.COLOR_MAGENTA,
            curses.COLOR_WHITE,
        ]

        for i, color in enumerate(colors):
            curses.init_pair(30 + i, color, -1)

        self._initialized = True


# Global registry
palette_registry = PaletteRegistry()
palette_registry.register(SpectrumPalette())
palette_registry.register(AgentPalette("claude"))
palette_registry.register(AgentPalette("gemini"))
palette_registry.register(AgentPalette("codex"))

# Section Palettes
# Indices: Red=0, Yellow=1, Green=2, Cyan=3, Blue=4, Magenta=5, White=6
palette_registry.register(SectionPalette("telegram", [4, 6]))  # Blue, White
palette_registry.register(SectionPalette("whatsapp", [2, 6]))  # Green, White (I6)
palette_registry.register(SectionPalette("discord", [4, 5, 6]))  # Blue, Magenta, White
palette_registry.register(SectionPalette("ai_keys", [2, 1]))  # Green, Yellow
palette_registry.register(SectionPalette("people", [6]))  # White
palette_registry.register(SectionPalette("notifications", [1, 6]))  # Yellow, White
palette_registry.register(SectionPalette("environment", [2, 3]))  # Green, Cyan
palette_registry.register(SectionPalette("validate", [2, 0]))  # Green, Red
