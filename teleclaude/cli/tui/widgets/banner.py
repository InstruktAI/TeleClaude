"""ASCII banner widget with optional animation color overlay."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from rich.style import Style
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_engine import AnimationEngine

BANNER_LINES = [
    " \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557      \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557",
    " \u255a\u2550\u2550\u2588\u2588\u2554\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d",
    "    \u2588\u2588\u2551   \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551     \u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2557  ",
    "    \u2588\u2588\u2551   \u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2551     \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u255d  ",
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


def _to_color(c: str | int | None) -> str | None:
    """Helper to ensure Style receives a valid color string or None."""
    if isinstance(c, str) and len(c) > 1:
        return c
    return None


def _is_pipe(c: str) -> bool:
    """True for double-line box-drawing connector characters (U+2550–U+256C)."""
    return len(c) == 1 and 0x2550 <= ord(c) <= 0x256C


def _dim_color(hex_color: str, factor: float) -> str:
    """Scale a #RRGGBB color's brightness by factor (e.g. 0.7 = 30% darker).

    Returns color unchanged if it's not a valid hex color format (e.g., color(N) palette strings).
    """
    # Guard against non-hex color formats (e.g., color(N) from animation engine)
    if not hex_color.startswith("#") or len(hex_color) != 7:
        return hex_color

    try:
        h = hex_color.lstrip("#")
        r = int(int(h[0:2], 16) * factor)
        g = int(int(h[2:4], 16) * factor)
        b = int(int(h[4:6], 16) * factor)
        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        # If parsing fails (malformed hex), return original color
        return hex_color


class Banner(TelecMixin, Widget):
    """ASCII art banner for the TUI header."""

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
        try:
            if self.is_compact:
                return self._render_logo()
            return self._render_banner()
        except Exception:
            logger.exception("Banner render crashed")
            return Text("TELECLAUDE")

    def _render_banner(self) -> Text:
        result = Text()
        engine = self.animation_engine
        from teleclaude.cli.tui.animations.base import Z_FOREGROUND, Z_SKY
        from teleclaude.cli.tui.pixel_mapping import PixelMap
        from teleclaude.cli.tui.theme import (
            BANNER_HEX,
            NEUTRAL_MUTED_COLOR,
            apply_tui_haze,
            blend_colors,
            deepen_for_light_mode,
            get_billboard_background,
            is_dark_mode,
            letter_color_floor,
        )

        focused = getattr(self.app, "app_focus", True)
        dark_mode = is_dark_mode()
        plate_bg = get_billboard_background(focused)
        pipe_color = NEUTRAL_MUTED_COLOR if focused else apply_tui_haze(NEUTRAL_MUTED_COLOR)
        sky_fallback = "#000000" if dark_mode else "#C8E8F8"

        # Full terminal width for sky
        total_width = self.size.width or 84

        for y in range(BANNER_HEIGHT):
            if y > 0:
                result.append("\n")

            if y < len(BANNER_LINES):
                line = BANNER_LINES[y]
                for x in range(total_width):
                    char = line[x] if x < len(line) else " "

                    # 1. Start with Base Atmosphere (Sky Z-0) from Global Header
                    bg_color = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                    if not isinstance(bg_color, str):
                        bg_color = sky_fallback

                    # 2. Billboard Plate (Z-3) Masks the Sky
                    # Plate spans x=0..84: one column of padding each side of the 84-char banner text
                    is_on_plate = x < 85
                    is_letter = PixelMap.get_is_letter("banner", x, y) if is_on_plate else False
                    final_bg = plate_bg if is_on_plate else bg_color

                    # 3. Foreground / Entities (Z-7) from Global Header
                    fg_char = char
                    fg_color = None
                    if engine:
                        entity_val = engine.get_layer_color(Z_FOREGROUND, x, y, target="header")
                        if entity_val and entity_val != -1:
                            # PHYSICAL MASKING: Stars/clouds ONLY show in empty space (inverse canvas)
                            if not is_on_plate:
                                if isinstance(entity_val, str) and len(entity_val) == 1:
                                    fg_char = entity_val
                                    # Sun disc chars (█) are yellow in light mode, white otherwise
                                    fg_color = "#FFD700" if (entity_val == "\u2588" and not dark_mode) else "#FFFFFF"
                                elif isinstance(entity_val, str):
                                    fg_color = entity_val

                    # 4. Final Compositing
                    if engine and engine.has_active_animation:
                        # Internal Neon Surge or External Reflective Light
                        color = engine.get_color(x, y, target="banner")
                        is_ext = engine.is_external_light(target="banner")

                        is_pipe_char = _is_pipe(char)
                        if color:
                            color_str = str(color)
                            if not focused:
                                color_str = apply_tui_haze(color_str)
                            # Letter pixels: dark mode → enforce floor; light mode → deepen for visibility
                            if is_letter:
                                if dark_mode:
                                    floor = BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)
                                    color_str = letter_color_floor(color_str, floor)
                                else:
                                    color_str = deepen_for_light_mode(color_str)
                            # Pipe connectors: 30% dimmer than fill pixels
                            if is_pipe_char:
                                color_str = _dim_color(color_str, 0.8)

                            if is_ext:
                                # Proportional Lighting on the final background
                                blend_pct = 0.5 if is_letter else 0.2
                                final_bg = blend_colors(str(final_bg), color_str, blend_pct)
                                result.append(fg_char, style=Style(color=color_str, bgcolor=_to_color(final_bg)))
                            else:
                                # Neon Internal Surge
                                result.append(fg_char, style=Style(color=color_str, bgcolor=_to_color(final_bg)))
                        else:
                            # Base State
                            fg = str(fg_color or (BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)))
                            if is_pipe_char:
                                fg = _dim_color(fg, 0.8)
                            result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
                    else:
                        is_pipe_char = _is_pipe(char)
                        fg = str(fg_color or (BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)))
                        if is_pipe_char:
                            fg = _dim_color(fg, 0.8)
                        result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
            else:
                # Row 6: Pipes under E (13) and D (70)
                for x in range(total_width):
                    if x == 13 or x == 70:
                        result.append("\u2551", style=pipe_color)
                    else:
                        # 1. Sky Z-0 between pipes
                        bg = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                        if not isinstance(bg, str):
                            bg = sky_fallback

                        # 2. Atmospheric entities (stars/clouds) - MASKED by pipes
                        fg_char = " "
                        fg_color = None
                        if engine:
                            entity_val = engine.get_layer_color(Z_FOREGROUND, x, y, target="header")
                            if entity_val and entity_val != -1:
                                if isinstance(entity_val, str) and len(entity_val) == 1:
                                    fg_char = entity_val
                                    fg_color = "#FFD700" if (entity_val == "\u2588" and not dark_mode) else "#FFFFFF"

                        result.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(bg)))

        return result

    def _render_logo(self) -> Text:
        result = Text()
        engine = self.animation_engine
        from teleclaude.cli.tui.animations.base import Z_FOREGROUND, Z_SKY
        from teleclaude.cli.tui.pixel_mapping import PixelMap
        from teleclaude.cli.tui.theme import (
            BANNER_HEX,
            NEUTRAL_MUTED_COLOR,
            apply_tui_haze,
            blend_colors,
            deepen_for_light_mode,
            get_billboard_background,
            is_dark_mode,
            letter_color_floor,
        )

        focused = getattr(self.app, "app_focus", True)
        dark_mode = is_dark_mode()
        plate_bg = get_billboard_background(focused)
        pipe_color = NEUTRAL_MUTED_COLOR if focused else apply_tui_haze(NEUTRAL_MUTED_COLOR)
        sky_fallback = "#000000" if dark_mode else "#C8E8F8"

        width = 40
        total_width = self.size.width or 40
        pad = max(0, total_width - width)

        for y in range(LOGO_HEIGHT):
            if y > 0:
                result.append("\n")

            if y < len(LOGO_LINES):
                line = LOGO_LINES[y]
                for x in range(total_width):
                    # 1. Sky Z-0 from Global Header
                    bg_color = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                    if not isinstance(bg_color, str):
                        bg_color = sky_fallback

                    # 2. Masking
                    is_on_plate = x >= pad and x < total_width
                    is_letter = PixelMap.get_is_letter("logo", x - pad, y) if is_on_plate else False
                    final_bg = plate_bg if is_on_plate else bg_color

                    # 3. Entities Z-7 from Global Header
                    fg_char = line[x - pad] if (is_on_plate and x - pad < len(line)) else " "
                    fg_color = None
                    if engine:
                        entity_val = engine.get_layer_color(Z_FOREGROUND, x, y, target="header")
                        if entity_val and entity_val != -1:
                            # PHYSICAL MASKING: Only show in non-physical margins
                            if not is_on_plate:
                                if isinstance(entity_val, str) and len(entity_val) == 1:
                                    fg_char = entity_val
                                    # Sun disc chars (█) are yellow in light mode, white otherwise
                                    fg_color = "#FFD700" if (entity_val == "\u2588" and not dark_mode) else "#FFFFFF"
                                elif isinstance(entity_val, str):
                                    fg_color = entity_val

                    is_pipe_char = _is_pipe(fg_char)
                    if engine and engine.has_active_animation:
                        color = engine.get_color(x - pad, y, target="logo") if is_on_plate else None
                        is_ext = engine.is_external_light(target="logo")

                        if color:
                            color_str = str(color)
                            if not focused:
                                color_str = apply_tui_haze(color_str)
                            # Letter pixels: dark mode → enforce floor; light mode → deepen for visibility
                            if is_letter:
                                if dark_mode:
                                    floor = BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)
                                    color_str = letter_color_floor(color_str, floor)
                                else:
                                    color_str = deepen_for_light_mode(color_str)
                            if is_pipe_char:
                                color_str = _dim_color(color_str, 0.8)

                            if is_ext:
                                blend_pct = 0.5 if is_letter else 0.2
                                final_bg = blend_colors(str(final_bg), color_str, blend_pct)
                                result.append(fg_char, style=Style(color=color_str, bgcolor=_to_color(final_bg)))
                            else:
                                result.append(fg_char, style=Style(color=color_str, bgcolor=_to_color(final_bg)))
                        else:
                            fg = str(fg_color or (BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)))
                            if is_pipe_char:
                                fg = _dim_color(fg, 0.8)
                            result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
                    else:
                        fg = str(fg_color or (BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)))
                        if is_pipe_char:
                            fg = _dim_color(fg, 0.8)
                        result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
            else:
                # Logo pipes: E(6), D(34)
                for x in range(total_width):
                    if (x >= pad and x < total_width) and (x - pad == 6 or x - pad == 34):
                        result.append("\u2551", style=pipe_color)
                    else:
                        bg = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                        if not isinstance(bg, str):
                            bg = sky_fallback

                        fg_char = " "
                        fg_color = None
                        if engine:
                            entity_val = engine.get_layer_color(Z_FOREGROUND, x, y, target="header")
                            if entity_val and entity_val != -1:
                                if isinstance(entity_val, str) and len(entity_val) == 1:
                                    fg_char = entity_val
                                    fg_color = "#FFD700" if (entity_val == "\u2588" and not dark_mode) else "#FFFFFF"

                        result.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(bg)))

        return result
