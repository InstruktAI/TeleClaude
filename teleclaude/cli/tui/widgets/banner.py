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
    """True for double-line box-drawing connector characters (U+2550-U+256C)."""
    return len(c) == 1 and 0x2550 <= ord(c) <= 0x256C


def _dim_color(hex_color: str, factor: float) -> str:
    """Scale a #RRGGBB color's brightness by factor (e.g. 0.7 = 30% darker)."""
    if not hex_color.startswith("#") or len(hex_color) != 7:
        return hex_color
    try:
        h = hex_color.lstrip("#")
        r = int(int(h[0:2], 16) * factor)
        g = int(int(h[2:4], 16) * factor)
        b = int(int(h[4:6], 16) * factor)
        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        return hex_color


def _entity_color(ch: str, z: int, dark_mode: bool) -> str:
    """Fallback color for old-style (uncolored) sky entity pixels."""
    return "#FFFFFF"


def _scan_sky_entity(
    engine: object, x: int, y: int, dark_mode: bool, z_levels: list[int]
) -> tuple[str, str | None, str | None]:
    """Scan Z-levels top-down for sky entities at (x, y).

    Returns (char, fg_color, bg_entity_color).
    bg_entity_color is the color of a deeper entity (e.g. sun behind cloud)
    for transparency compositing.  Defaults to (" ", None, None).

    Buffer value encoding:
      - 1 char: old-style entity char (color from _entity_color)
      - 2 chars starting with \\x01: old-style inverted char
      - 7 chars starting with #: pure color (glow/ambient)
      - 8 chars starting with #: colored entity char (#RRGGBBc)
      - 9 chars starting with \\x01#: colored inverted char (\\x01#RRGGBBc)
      - 15 chars #fg#bg + ch: fully resolved sprite pixel (both colors from layers)

    For inverted (negative) partial-block chars, the cutout reveals whatever
    is behind: scanning continues to deeper Z-levels to find the behind color
    instead of hardcoding the sky gradient.
    """
    from teleclaude.cli.tui.animations.base import Z_SKY

    fg_char = " "
    fg_color: str | None = None
    bg_entity_color: str | None = None
    # Set when the topmost entity is a negative partial-block: need to find
    # the color that shows through the cutout from deeper Z-levels.
    need_behind = False

    for z in z_levels:
        val = engine.get_layer_color(z, x, y, target="header")  # type: ignore[union-attr]
        if not val or val == -1:
            continue
        if not isinstance(val, str):
            continue

        vlen = len(val)

        # --- Fully resolved sprite pixel (pre-composited layers) ---
        if vlen == 15 and val[0] == "#" and val[7] == "#":
            # "#fg_color#bg_colorc" — both colors from sprite, no scene needed
            fg_val, bg_val, ch = val[0:7], val[7:14], val[14]
            if need_behind:
                fg_color = fg_val
                break
            elif fg_char == " ":
                fg_char = ch
                fg_color = fg_val
                bg_entity_color = bg_val
                break
            else:
                bg_entity_color = bg_val
                break

        # --- Colored composite sprite chars (from layered CompositeSprite) ---
        elif vlen == 8 and val[0] == "#":
            # Positive colored char: "#RRGGBBc" → fg = color, char = c
            color, ch = val[:7], val[7]
            if need_behind:
                fg_color = color
                break
            elif fg_char == " ":
                fg_char = ch
                fg_color = color
            else:
                bg_entity_color = color
                break

        elif vlen == 9 and val[0] == "\x01" and val[1] == "#":
            # Negative colored char: "\x01#RRGGBBc" → inverted rendering
            color, ch = val[1:8], val[8]
            if ch == "\u2588":
                # Full block: solid fill, no cutout
                if need_behind:
                    fg_color = color
                    break
                elif fg_char == " ":
                    fg_char = ch
                    fg_color = color
                else:
                    bg_entity_color = color
                    break
            else:
                # Partial block: cutout reveals what's behind
                if need_behind:
                    fg_color = color
                    break
                elif fg_char == " ":
                    fg_char = ch
                    bg_entity_color = color
                    need_behind = True
                    # Continue scanning for behind color
                else:
                    bg_entity_color = color
                    break

        # --- Old-style uncolored chars (clouds, stars, celestial) ---
        elif vlen == 1:
            ec = _entity_color(val, z, dark_mode)
            if need_behind:
                fg_color = ec
                break
            elif fg_char == " ":
                fg_char = val
                fg_color = ec
            else:
                bg_entity_color = ec
                break

        elif vlen == 2 and val[0] == "\x01":
            # Old-style inverted char
            ch = val[1]
            ec = _entity_color(ch, z, dark_mode)
            if ch == "\u2588":
                if need_behind:
                    fg_color = ec
                    break
                elif fg_char == " ":
                    fg_char = ch
                    fg_color = ec
                else:
                    bg_entity_color = ec
                    break
            else:
                if need_behind:
                    fg_color = ec
                    break
                elif fg_char == " ":
                    fg_char = ch
                    bg_entity_color = ec
                    need_behind = True
                else:
                    bg_entity_color = ec
                    break

        elif vlen == 7 and val[0] == "#":
            # Pure color string (glow/ambient)
            if need_behind:
                fg_color = val
                break
            elif fg_color is None:
                fg_color = val
            else:
                bg_entity_color = val
                break

    # Fallback: negative char found but nothing behind — use sky gradient
    if need_behind and fg_color is None:
        sky_val = engine.get_layer_color(Z_SKY, x, y, target="header")  # type: ignore[union-attr]
        fg_color = sky_val if isinstance(sky_val, str) else None

    return fg_char, fg_color, bg_entity_color


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
        from teleclaude.cli.tui.animations.base import Z_SKY
        from teleclaude.cli.tui.pixel_mapping import PixelMap
        from teleclaude.cli.tui.theme import (
            blend_colors,
            deepen_for_light_mode,
            get_banner_hex,
            get_billboard_background,
            get_neutral_color,
            is_dark_mode,
            letter_color_floor,
            resolve_haze,
        )

        dark_mode = is_dark_mode()
        plate_bg = get_billboard_background()
        pipe_color = resolve_haze(get_neutral_color("muted"))
        sky_fallback = "#000000" if dark_mode else "#C8E8F8"

        total_width = self.size.width or 84
        z_levels = engine.get_entity_z_levels("header") if engine else []

        for y in range(BANNER_HEIGHT):
            if y > 0:
                result.append("\n")

            if y < len(BANNER_LINES):
                line = BANNER_LINES[y]
                for x in range(total_width):
                    char = line[x] if x < len(line) else " "

                    # 1. Sky Z-0
                    bg_color = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                    if not isinstance(bg_color, str):
                        bg_color = sky_fallback

                    # 2. Billboard plate masks sky
                    is_on_plate = x < 85
                    is_letter = PixelMap.get_is_letter("banner", x, y) if is_on_plate else False
                    final_bg = plate_bg if is_on_plate else bg_color

                    # 3. Multi-Z entity scan in sky margins
                    fg_char = char
                    fg_color: str | None = None
                    bg_entity_color: str | None = None
                    if engine and not is_on_plate:
                        fg_char, fg_color, bg_entity_color = _scan_sky_entity(engine, x, y, dark_mode, z_levels)
                        if bg_entity_color:
                            final_bg = bg_entity_color

                    # 4. Final compositing
                    if engine and engine.has_active_animation:
                        color = engine.get_color(x, y, target="banner")
                        is_ext = engine.is_external_light(target="banner")

                        is_pipe_char = _is_pipe(char)
                        if color:
                            color_str = resolve_haze(str(color))
                            if is_letter:
                                if dark_mode:
                                    color_str = letter_color_floor(color_str, resolve_haze(get_banner_hex()))
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
                            fg = str(fg_color or resolve_haze(get_banner_hex()))
                            if _is_pipe(char):
                                fg = _dim_color(fg, 0.8)
                            result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
                    else:
                        is_pipe_char = _is_pipe(char)
                        fg = str(fg_color or resolve_haze(get_banner_hex()))
                        if is_pipe_char:
                            fg = _dim_color(fg, 0.8)
                        result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
            else:
                # Row 6: Pipes under E (13) and D (70)
                for x in range(total_width):
                    if x == 13 or x == 70:
                        result.append("\u2551", style=pipe_color)
                    else:
                        bg = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                        if not isinstance(bg, str):
                            bg = sky_fallback

                        fg_char = " "
                        fg_color = None
                        if engine:
                            fg_char, fg_color, bg_ent = _scan_sky_entity(engine, x, y, dark_mode, z_levels)
                            if bg_ent:
                                bg = bg_ent

                        result.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(bg)))

        return result

    def _render_logo(self) -> Text:
        result = Text()
        engine = self.animation_engine
        from teleclaude.cli.tui.animations.base import Z_SKY
        from teleclaude.cli.tui.pixel_mapping import PixelMap
        from teleclaude.cli.tui.theme import (
            blend_colors,
            deepen_for_light_mode,
            get_banner_hex,
            get_billboard_background,
            get_neutral_color,
            is_dark_mode,
            letter_color_floor,
            resolve_haze,
        )

        dark_mode = is_dark_mode()
        plate_bg = get_billboard_background()
        pipe_color = resolve_haze(get_neutral_color("muted"))
        sky_fallback = "#000000" if dark_mode else "#C8E8F8"

        width = 40
        total_width = self.size.width or 40
        pad = max(0, total_width - width)
        z_levels = engine.get_entity_z_levels("header") if engine else []

        for y in range(LOGO_HEIGHT):
            if y > 0:
                result.append("\n")

            if y < len(LOGO_LINES):
                line = LOGO_LINES[y]
                for x in range(total_width):
                    bg_color = engine.get_layer_color(Z_SKY, x, y, target="header") if engine else None
                    if not isinstance(bg_color, str):
                        bg_color = sky_fallback

                    is_on_plate = x >= pad and x < total_width
                    is_letter = PixelMap.get_is_letter("logo", x - pad, y) if is_on_plate else False
                    final_bg = plate_bg if is_on_plate else bg_color

                    fg_char = line[x - pad] if (is_on_plate and x - pad < len(line)) else " "
                    fg_color: str | None = None
                    bg_entity_color: str | None = None
                    if engine and not is_on_plate:
                        fg_char, fg_color, bg_entity_color = _scan_sky_entity(engine, x, y, dark_mode, z_levels)
                        if bg_entity_color:
                            final_bg = bg_entity_color

                    is_pipe_char = _is_pipe(fg_char)
                    if engine and engine.has_active_animation:
                        color = engine.get_color(x - pad, y, target="logo") if is_on_plate else None
                        is_ext = engine.is_external_light(target="logo")

                        if color:
                            color_str = resolve_haze(str(color))
                            if is_letter:
                                if dark_mode:
                                    color_str = letter_color_floor(color_str, resolve_haze(get_banner_hex()))
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
                            fg = str(fg_color or resolve_haze(get_banner_hex()))
                            if is_pipe_char:
                                fg = _dim_color(fg, 0.8)
                            result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))
                    else:
                        fg = str(fg_color or resolve_haze(get_banner_hex()))
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
                            fg_char, fg_color, bg_ent = _scan_sky_entity(engine, x, y, dark_mode, z_levels)
                            if bg_ent:
                                bg = bg_ent

                        result.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(bg)))

        return result
