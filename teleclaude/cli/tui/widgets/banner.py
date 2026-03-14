"""ASCII banner widget with optional animation color overlay."""

from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from rich.style import Style
from rich.text import Text
from textual.events import Click
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

SPRITES_URL = "https://github.com/InstruktAI/TeleClaude/tree/main/teleclaude/cli/tui/animations/sprites"


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
    """Default white color for old-style (uncolored) sky entity pixels."""
    return "#FFFFFF"


def _scan_sky_entity(
    engine: object, x: int, y: int, dark_mode: bool, z_levels: list[int], z_min: int = 0
) -> tuple[str, str | None, str | None]:
    """Scan Z-levels top-down for sky entities at (x, y).

    Returns (char, fg_color, bg_entity_color).
    bg_entity_color is the color of a deeper entity (e.g. sun behind cloud)
    for transparency compositing.  Defaults to (" ", None, None).
    z_min: only consider entities above this Z-level.

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
    from teleclaude.cli.tui.animations.base import Z0

    state: dict[str, str | bool | None] = {
        "fg_char": " ",
        "fg_color": None,
        "bg_entity_color": None,
        "need_behind": False,
    }

    for z in z_levels:
        if z <= z_min:
            break
        val = engine.get_layer_color(z, x, y, target="header")  # type: ignore[union-attr]
        if not val or val == -1:
            continue
        if not isinstance(val, str):
            continue
        if _consume_sky_entity_value(state, val, z, dark_mode):
            break

    # Negative char found but nothing behind — use sky gradient
    if state["need_behind"] and state["fg_color"] is None:
        sky_val = engine.get_layer_color(Z0, x, y, target="header")  # type: ignore[union-attr]
        state["fg_color"] = sky_val if isinstance(sky_val, str) else None

    return (
        str(state["fg_char"]),
        state["fg_color"] if isinstance(state["fg_color"], str) else None,
        state["bg_entity_color"] if isinstance(state["bg_entity_color"], str) else None,
    )


def _consume_sky_entity_value(state: dict[str, str | bool | None], val: str, z: int, dark_mode: bool) -> bool:
    vlen = len(val)
    if vlen == 15 and val[0] == "#" and val[7] == "#":
        return _apply_sky_entity(state, val[14], val[0:7], val[7:14], partial=False)
    if vlen == 8 and val[0] == "#":
        return _apply_sky_entity(state, val[7], val[:7], val[:7], partial=False)
    if vlen == 9 and val[0] == "\x01" and val[1] == "#":
        return _apply_sky_entity(state, val[8], val[1:8], val[1:8], partial=val[8] != "\u2588")
    if vlen == 1:
        entity_color = _entity_color(val, z, dark_mode)
        return _apply_sky_entity(state, val, entity_color, entity_color, partial=False)
    if vlen == 2 and val[0] == "\x01":
        ch = val[1]
        entity_color = _entity_color(ch, z, dark_mode)
        return _apply_sky_entity(state, ch, entity_color, entity_color, partial=ch != "\u2588")
    if vlen == 7 and val[0] == "#":
        return _apply_sky_ambient(state, val)
    return False


def _apply_sky_entity(
    state: dict[str, str | bool | None],
    ch: str,
    fg_color: str,
    bg_color: str,
    *,
    partial: bool,
) -> bool:
    if state["need_behind"]:
        state["fg_color"] = fg_color
        return True
    if state["fg_char"] != " ":
        state["bg_entity_color"] = bg_color
        return True
    state["fg_char"] = ch
    if partial:
        state["bg_entity_color"] = bg_color
        state["need_behind"] = True
        return False
    state["fg_color"] = fg_color
    if bg_color != fg_color:
        state["bg_entity_color"] = bg_color
        return True
    return False


def _apply_sky_ambient(state: dict[str, str | bool | None], color: str) -> bool:
    if state["need_behind"]:
        state["fg_color"] = color
        return True
    if state["fg_color"] is None:
        state["fg_color"] = color
        return False
    state["bg_entity_color"] = color
    return True


def _resolve_sky_background(engine: AnimationEngine | None, x: int, y: int, sky_fallback: str) -> str:
    from teleclaude.cli.tui.animations.base import Z0

    bg_color = engine.get_layer_color(Z0, x, y, target="header") if engine else None
    return bg_color if isinstance(bg_color, str) else sky_fallback


def _render_art_content(
    result: Text,
    *,
    lines: list[str],
    total_width: int,
    pad: int,
    target: str,
    plate_width: int,
    engine: AnimationEngine | None,
    dark_mode: bool,
    plate_bg: str,
    sky_fallback: str,
    z_levels: list[int],
) -> None:
    from teleclaude.cli.tui.animations.base import Z50
    from teleclaude.cli.tui.pixel_mapping import PixelMap
    from teleclaude.cli.tui.theme import (
        get_banner_hex,
        resolve_haze,
    )

    for y, line in enumerate(lines):
        if y > 0:
            result.append("\n")
        for x in range(total_width):
            local_x = x - pad
            is_on_plate = pad <= x < pad + plate_width
            fg_char = line[local_x] if is_on_plate and local_x < len(line) else " "
            final_bg = plate_bg if is_on_plate else _resolve_sky_background(engine, x, y, sky_fallback)
            fg_color: str | None = None
            entity_override = False
            if engine:
                z_threshold = Z50 if is_on_plate else 0
                ent_char, ent_fg, bg_entity_color = _scan_sky_entity(
                    engine, x, y, dark_mode, z_levels, z_min=z_threshold
                )
                if ent_char != " ":
                    fg_char = ent_char
                    fg_color = ent_fg
                    entity_override = True
                if bg_entity_color:
                    final_bg = bg_entity_color
            if _append_animation_pixel(
                result,
                fg_char=fg_char,
                fg_color=fg_color,
                final_bg=final_bg,
                x=x,
                y=y,
                local_x=local_x,
                target=target,
                is_on_plate=is_on_plate,
                is_letter=PixelMap.get_is_letter(target, local_x, y) if is_on_plate else False,
                entity_override=entity_override,
                engine=engine,
                dark_mode=dark_mode,
            ):
                continue
            fg = str(fg_color or resolve_haze(get_banner_hex()))
            if not entity_override and _is_pipe(fg_char):
                fg = _dim_color(fg, 0.8)
            result.append(fg_char, style=Style(color=fg, bgcolor=_to_color(final_bg)))


def _append_animation_pixel(
    result: Text,
    *,
    fg_char: str,
    fg_color: str | None,
    final_bg: str,
    x: int,
    y: int,
    local_x: int,
    target: str,
    is_on_plate: bool,
    is_letter: bool,
    entity_override: bool,
    engine: AnimationEngine | None,
    dark_mode: bool,
) -> bool:
    from teleclaude.cli.tui.theme import (
        blend_colors,
        deepen_for_light_mode,
        get_banner_hex,
        letter_color_floor,
        resolve_haze,
    )

    if not (engine and engine.has_active_animation and is_on_plate):
        return False
    color = engine.get_color(local_x, y, target=target)
    if not color or entity_override:
        return False
    color_str = resolve_haze(str(color))
    if is_letter:
        color_str = (
            letter_color_floor(color_str, resolve_haze(get_banner_hex()))
            if dark_mode
            else deepen_for_light_mode(color_str)
        )
    if _is_pipe(fg_char):
        color_str = _dim_color(color_str, 0.8)
    if engine.is_external_light(target=target):
        blend_pct = 0.5 if is_letter else 0.2
        final_bg = blend_colors(str(final_bg), color_str, blend_pct)
    result.append(fg_char, style=Style(color=color_str, bgcolor=_to_color(final_bg)))
    return True


def _render_pipe_row(
    result: Text,
    *,
    total_width: int,
    y: int,
    engine: AnimationEngine | None,
    dark_mode: bool,
    z_levels: list[int],
    sky_fallback: str,
    pipe_positions: set[int],
    pipe_color: str,
    z_threshold: int,
) -> None:
    for x in range(total_width):
        bg = _resolve_sky_background(engine, x, y, sky_fallback)
        is_pipe = x in pipe_positions
        fg_char = "\u2551" if is_pipe else " "
        fg_color: str | None = str(pipe_color) if is_pipe else None
        if engine:
            ent_char, ent_color, bg_ent = _scan_sky_entity(
                engine,
                x,
                y,
                dark_mode,
                z_levels,
                z_min=z_threshold if is_pipe else 0,
            )
            if ent_char != " ":
                fg_char = ent_char
                fg_color = ent_color
            if bg_ent:
                bg = bg_ent
        result.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(bg)))


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

    def on_click(self, event: Click) -> None:
        """Open the sprites README on GitHub when the banner plate is clicked."""
        x = event.x
        if self.is_compact:
            total_width = self.size.width or 40
            pad = max(0, total_width - LOGO_WIDTH)
            if x < pad or x >= pad + LOGO_WIDTH:
                return
        else:
            if x >= 85:
                return
        try:
            webbrowser.open(SPRITES_URL)
        except Exception:
            logger.exception("Failed to open sprites URL")

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
        from teleclaude.cli.tui.animations.base import Z50
        from teleclaude.cli.tui.theme import (
            get_billboard_background,
            get_neutral_color,
            is_dark_mode,
            resolve_haze,
        )

        dark_mode = is_dark_mode()
        plate_bg = get_billboard_background()
        pipe_color = resolve_haze(get_neutral_color("muted"))
        sky_fallback = "#000000" if dark_mode else "#C8E8F8"

        total_width = self.size.width or 84
        z_levels = engine.get_entity_z_levels("header") if engine else []
        _render_art_content(
            result,
            lines=BANNER_LINES,
            total_width=total_width,
            pad=0,
            target="banner",
            plate_width=85,
            engine=engine,
            dark_mode=dark_mode,
            plate_bg=plate_bg,
            sky_fallback=sky_fallback,
            z_levels=z_levels,
        )
        result.append("\n")
        _render_pipe_row(
            result,
            total_width=total_width,
            y=len(BANNER_LINES),
            engine=engine,
            dark_mode=dark_mode,
            z_levels=z_levels,
            sky_fallback=sky_fallback,
            pipe_positions={13, 70},
            pipe_color=pipe_color,
            z_threshold=Z50,
        )

        return result

    def _render_logo(self) -> Text:
        result = Text()
        engine = self.animation_engine
        from teleclaude.cli.tui.animations.base import Z50
        from teleclaude.cli.tui.theme import (
            get_billboard_background,
            get_neutral_color,
            is_dark_mode,
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
        _render_art_content(
            result,
            lines=LOGO_LINES,
            total_width=total_width,
            pad=pad,
            target="logo",
            plate_width=width,
            engine=engine,
            dark_mode=dark_mode,
            plate_bg=plate_bg,
            sky_fallback=sky_fallback,
            z_levels=z_levels,
        )
        result.append("\n")
        _render_pipe_row(
            result,
            total_width=total_width,
            y=len(LOGO_LINES),
            engine=engine,
            dark_mode=dark_mode,
            z_levels=z_levels,
            sky_fallback=sky_fallback,
            pipe_positions={pad + 6, pad + 34},
            pipe_color=pipe_color,
            z_threshold=Z50,
        )

        return result
