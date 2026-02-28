"""ASCII banner widget with optional animation color overlay."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import BANNER_COLOR

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_engine import AnimationEngine

BANNER_LINES = [
    " \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557      \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557",
    " \u255a\u2550\u2550\u2588\u2588\u2554\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d",
    "    \u2588\u2588\u2551   \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551     \u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2557  ",
    "    \u2588\u2588\u2551   \u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2551     \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u255d  ",
    "    \u2588\u2588\u2551   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557",
    "    \u255a\u2550\u255d   \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d",
]

LOGO_LINES = [
    " \u2580\u2588\u2580 \u259b\u2580\u2580 \u258c   \u259b\u2580\u2580 \u259b\u2580\u259c \u258c   \u259e\u2580\u259a \u258c \u2590 \u259b\u2580\u259a \u259b\u2580\u2580",
    "  \u2588  \u25a0\u25a0  \u258c   \u25a0\u25a0  \u258c   \u258c   \u2599\u2584\u259f \u258c \u2590 \u258c \u2590 \u25a0\u25a0",
    "  \u2588  \u2599\u2584\u2584 \u2599\u2584\u2584 \u2599\u2584\u2584 \u2599\u2584\u259f \u2599\u2584\u2584 \u258c \u2590 \u259a\u2584\u259e \u259a\u2584\u259e \u2599\u2584\u2584",
]

BANNER_HEIGHT = len(BANNER_LINES) + 1
LOGO_HEIGHT = len(LOGO_LINES) + 1
LOGO_WIDTH = 40


class Banner(TelecMixin, Widget):
    """ASCII art banner for the TUI header.

    Switches between a full 6-line banner and a compact 3-line logo
    based on the ``is_compact`` property. When pane count makes the TUI
    small (2x2 or 3x2 grids), compact mode saves vertical space.

    When an AnimationEngine is attached, per-character color overlays
    from the engine replace the default BANNER_COLOR during rendering.
    Uses target="banner" for full mode, target="logo" for compact mode.
    """

    DEFAULT_CSS = """
    Banner {
        width: 100%;
        height: 7;
        content-align: left middle;
    }
    """

    is_compact = reactive(False)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.animation_engine: AnimationEngine | None = None

    def watch_is_compact(self, value: bool) -> None:
        """Update widget height when compactness changes."""
        self.styles.height = LOGO_HEIGHT if value else BANNER_HEIGHT

    def render(self) -> Text:
        if self.is_compact:
            return self._render_logo()
        return self._render_banner()

    def _render_banner(self) -> Text:
        result = Text()
        engine = self.animation_engine
        from teleclaude.cli.tui.theme import (
            BANNER_COLOR,
            NEUTRAL_MUTED_COLOR,
            NEUTRAL_NORMAL_COLOR,
            NEUTRAL_SUBTLE_COLOR,
            is_dark_mode,
        )

        dark = is_dark_mode()
        # Billboard Plate: Lighter gray than bg in Night, Darker gray in Day
        plate_bg = "#262626" if dark else "#303030"
        outline_color = NEUTRAL_NORMAL_COLOR if dark else None
        pipe_color = NEUTRAL_MUTED_COLOR

        width = 83  # Shifted width

        for y in range(BANNER_HEIGHT):
            if y > 0:
                result.append("\n")

            if y < len(BANNER_LINES):
                line = BANNER_LINES[y]
                for x in range(width):
                    char = line[x] if x < len(line) else " "

                    # Billboard logic: Dark Mode Outline vs Day Mode Solid
                    is_edge = x == 0 or x == width - 1 or y == 0 or y == len(BANNER_LINES) - 1
                    style_color = outline_color if (dark and is_edge) else BANNER_COLOR
                    bg_color = plate_bg

                    if engine and engine.has_active_animation:
                        color = engine.get_color(x, y, target="banner")
                        if color:
                            result.append(char, style=Style(color=color, bgcolor=bg_color))
                        else:
                            result.append(char, style=Style(color=style_color, bgcolor=bg_color))
                    else:
                        result.append(char, style=Style(color=style_color, bgcolor=bg_color))
            else:
                # Pipes under E (13) and D (70)
                for x in range(width):
                    if x == 13 or x == 70:
                        result.append("\u2551", style=pipe_color)
                    else:
                        result.append(" ")

        return result

    def _render_logo(self) -> Text:
        result = Text()
        engine = self.animation_engine
        from teleclaude.cli.tui.theme import (
            BANNER_COLOR,
            NEUTRAL_MUTED_COLOR,
            NEUTRAL_NORMAL_COLOR,
            NEUTRAL_SUBTLE_COLOR,
            is_dark_mode,
        )

        dark = is_dark_mode()
        # Billboard Plate: Lighter gray than bg in Night, Darker gray in Day
        plate_bg = "#262626" if dark else "#303030"
        outline_color = NEUTRAL_NORMAL_COLOR if dark else None
        pipe_color = NEUTRAL_MUTED_COLOR

        width = 40
        tui_width = self.size.width
        pad = max(0, tui_width - width)

        for y in range(LOGO_HEIGHT):
            if y > 0:
                result.append("\n")

            result.append(" " * pad)

            if y < len(LOGO_LINES):
                line = LOGO_LINES[y]
                for x in range(width):
                    char = line[x] if x < len(line) else " "

                    is_edge = x == 0 or x == width - 1 or y == 0 or y == len(LOGO_LINES) - 1
                    style_color = outline_color if (dark and is_edge) else BANNER_COLOR
                    bg_color = plate_bg

                    if engine and engine.has_active_animation:
                        color = engine.get_color(x, y, target="logo")
                        if color:
                            result.append(char, style=Style(color=color, bgcolor=bg_color))
                        else:
                            result.append(char, style=Style(color=style_color, bgcolor=bg_color))
                    else:
                        result.append(char, style=Style(color=style_color, bgcolor=bg_color))
            else:
                # Logo pipes: E(6), D(34)
                for x in range(width):
                    if x == 6 or x == 34:
                        result.append("\u2551", style=pipe_color)
                    else:
                        result.append(" ")

        return result
