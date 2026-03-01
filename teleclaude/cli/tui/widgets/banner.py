"""ASCII banner widget with optional animation color overlay."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_engine import AnimationEngine

BANNER_LINES = [
    " \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557      \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557",
    " \u255a\u2550\u2550\u2588\u2588\u2554\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d",
    "    \u2588\u2588\u2551   \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551     \u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2557  ",
    "    \u2588\u2588\u2551   \u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2551     \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u255d  ",
    "    \u2588\u2588\u2551   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557",
    "    \u255a\u255d   \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d",
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
        if self.is_compact:
            return self._render_logo()
        return self._render_banner()

    def _render_banner(self) -> Text:
        result = Text()
        engine = self.animation_engine
        from teleclaude.cli.tui.theme import (
            BANNER_HEX,
            NEUTRAL_MUTED_COLOR,
            apply_tui_haze,
            blend_colors,
            get_billboard_background,
        )
        from teleclaude.cli.tui.pixel_mapping import PixelMap
        from teleclaude.cli.tui.animations.base import Z_SKY, Z_BILLBOARD, Z_FOREGROUND

        focused = getattr(self.app, "app_focus", True)
        plate_bg = get_billboard_background(focused)
        pipe_color = NEUTRAL_MUTED_COLOR if focused else apply_tui_haze(NEUTRAL_MUTED_COLOR)

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
                        bg_color = "#000000" if focused else "#050505"
                    
                    # 2. Billboard Plate (Z-3) Masks the Sky
                    is_on_plate = (x >= 1 and x < 83)
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
                                    fg_color = "#FFFFFF"
                                elif isinstance(entity_val, str):
                                    fg_color = entity_val

                    # 4. Final Compositing
                    if engine and engine.has_active_animation:
                        # Internal Neon Surge or External Reflective Light
                        color = engine.get_color(x, y, target="banner")
                        is_ext = engine.is_external_light(target="banner")
                        
                        if color and color != -1:
                            color_str = str(color)
                            if not focused: color_str = apply_tui_haze(color_str)
                            
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
                            result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
                    else:
                        fg = str(fg_color or (BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)))
                        result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
            else:
                # Row 6: Pipes under E (13) and D (70)
                for x in range(total_width):
                    if x == 13 or x == 70:
                        result.append("\u2551", style=pipe_color)
                    else:
                        # 1. Sky Z-0 between pipes
                        bg = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                        if not isinstance(bg, str): bg = "#000000"
                        
                        # 2. Atmospheric entities (stars/clouds) - MASKED by pipes
                        fg_char = " "
                        fg_color = None
                        if engine:
                            entity_val = engine.get_layer_color(Z_FOREGROUND, x, y, target="header")
                            if entity_val and entity_val != -1:
                                if isinstance(entity_val, str) and len(entity_val) == 1:
                                    fg_char = entity_val
                                    fg_color = "#FFFFFF"
                        
                        result.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(bg)))

        return result

    def _render_logo(self) -> Text:
        result = Text()
        engine = self.animation_engine
        from teleclaude.cli.tui.theme import (
            BANNER_HEX,
            NEUTRAL_MUTED_COLOR,
            apply_tui_haze,
            blend_colors,
            get_billboard_background,
        )
        from teleclaude.cli.tui.pixel_mapping import PixelMap
        from teleclaude.cli.tui.animations.base import Z_SKY, Z_FOREGROUND

        focused = getattr(self.app, "app_focus", True)
        plate_bg = get_billboard_background(focused)
        pipe_color = NEUTRAL_MUTED_COLOR if focused else apply_tui_haze(NEUTRAL_MUTED_COLOR)

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
                        bg_color = "#000000" if focused else "#050505"
                    
                    # 2. Masking
                    is_on_plate = (x >= pad and x < total_width)
                    is_letter = PixelMap.get_is_letter("logo", x - pad, y) if is_on_plate else False
                    final_bg = plate_bg if is_on_plate else bg_color

                    # 3. Entities Z-7 from Global Header
                    fg_char = line[x-pad] if (is_on_plate and x-pad < len(line)) else " "
                    fg_color = None
                    if engine:
                        entity_val = engine.get_layer_color(Z_FOREGROUND, x, y, target="header")
                        if entity_val and entity_val != -1:
                            # PHYSICAL MASKING: Only show in non-physical margins
                            if not is_on_plate:
                                if isinstance(entity_val, str) and len(entity_val) == 1:
                                    fg_char = entity_val
                                    fg_color = "#FFFFFF"
                                elif isinstance(entity_val, str):
                                    fg_color = entity_val

                    if engine and engine.has_active_animation:
                        color = engine.get_color(x - pad, y, target="logo") if is_on_plate else None
                        is_ext = engine.is_external_light(target="logo")
                        
                        if color and color != -1:
                            color_str = str(color)
                            if not focused: color_str = apply_tui_haze(color_str)
                            
                            if is_ext:
                                blend_pct = 0.5 if is_letter else 0.2
                                final_bg = blend_colors(str(final_bg), color_str, blend_pct)
                                result.append(fg_char, style=Style(color=color_str, bgcolor=_to_color(final_bg)))
                            else:
                                result.append(fg_char, style=Style(color=color_str, bgcolor=_to_color(final_bg)))
                        else:
                            fg = str(fg_color or (BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)))
                            result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
                    else:
                        fg = str(fg_color or (BANNER_HEX if focused else apply_tui_haze(BANNER_HEX)))
                        result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
            else:
                # Logo pipes: E(6), D(34)
                for x in range(total_width):
                    if is_on_plate and (x - pad == 6 or x - pad == 34):
                        result.append("\u2551", style=pipe_color)
                    else:
                        bg = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                        if not isinstance(bg, str): bg = "#000000"
                        
                        fg_char = " "
                        fg_color = None
                        if engine:
                            entity_val = engine.get_layer_color(Z_FOREGROUND, x, y, target="header")
                            if entity_val and entity_val != -1:
                                if isinstance(entity_val, str) and len(entity_val) == 1:
                                    fg_char = entity_val
                                    fg_color = "#FFFFFF"
                        
                        result.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(bg)))

        return result
