"""Box-drawing tab bar matching old curses TUI style."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import (
    blend_colors,
    get_neutral_color,
    get_terminal_background,
    get_tui_inactive_background,
    is_dark_mode,
    resolve_haze,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_engine import AnimationEngine


def _to_color(c: str | int | None) -> str | None:
    """Helper to ensure Style receives a valid color string or None."""
    if isinstance(c, str) and len(c) > 1:
        return c
    return None


def _scan_entity_at(
    engine: AnimationEngine,
    entity_z_scan: list[int],
    x: int,
    global_y: int,
    z_min: int,
    scene_bg: str,
) -> tuple[str | None, str | None, str | None] | None:
    """Scan for entity above z_min at (x, global_y).

    Returns (fg_char, fg_color, bg_color) or None.
    fg_char=None means bg-only (ambient glow).
    scene_bg: the background color of the row at this pixel (sky, bar, tab).

    Scene-transparent pixels (9-char encoding) are composited: the scan
    continues to lower Z levels so entities behind show through windows.
    """
    pending: tuple[str, str] | None = None  # (char, bg_color) from topmost transparent pixel
    for z in entity_z_scan:
        if z <= z_min:
            break
        val = engine.get_layer_color(z, x, global_y, target="header")
        if val and val != -1 and isinstance(val, str):
            elen = len(val)
            if elen == 15 and val[0] == "#" and val[7] == "#":
                if pending:
                    return pending[0], val[0:7], pending[1]
                return val[14], val[0:7], val[7:14]
            if elen == 8 and val[0] == "#":
                if pending:
                    return pending[0], val[0:7], pending[1]
                return val[7], val[0:7], None
            if elen == 9 and val[0] == "\x01" and val[1] == "#":
                if pending is None:
                    pending = (val[8], val[1:8])
                continue
            if elen == 7 and val[0] == "#":
                if pending:
                    return pending[0], val, pending[1]
                return None, None, val
            if elen == 1:
                if pending:
                    return pending[0], "#FFFFFF", pending[1]
                return val, "#FFFFFF", None
            break
    if pending:
        return pending[0], scene_bg, pending[1]
    return None


class BoxTabBar(TelecMixin, Widget):
    """Tab bar: sky row, label row, half-block transition row."""

    TABS = [
        ("sessions", "[1] AI Sessions"),
        ("preparation", "[2] Work Preparation"),
        ("jobs", "[3] Jobs"),
        ("config", "[4] Configuration"),
    ]

    DEFAULT_CSS = """
    BoxTabBar {
        width: 100%;
        height: 3;
    }
    """

    active_tab = reactive("sessions")

    class TabClicked(Message):
        """Posted when a tab is clicked."""

        def __init__(self, tab_id: str) -> None:
            super().__init__()
            self.tab_id = tab_id

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.animation_engine: AnimationEngine | None = None
        self._click_regions: list[tuple[int, int, str]] = []

    def on_mount(self) -> None:
        pass

    def render(self) -> Group:
        try:
            return self._render_tabs()
        except Exception:
            logger.exception("BoxTabBar render crashed")
            return Group()

    def _render_tabs(self) -> Group:
        width = self.size.width or 80
        engine = self.animation_engine
        dark_mode = is_dark_mode()
        from teleclaude.cli.tui.animations.base import Z60, Z70, Z80

        sky_fallback = "#000000" if dark_mode else "#C8E8F8"

        pane_bg = resolve_haze(get_terminal_background())
        pipe_color = resolve_haze(get_neutral_color("muted"))

        num_rows = 3  # sky, label, transition
        tab_gap = 1

        if dark_mode:
            active_tab_bg = "#FFFFFF"
            active_tab_fg = "#000000"
        else:
            active_tab_bg = pane_bg
            active_tab_fg = resolve_haze(get_neutral_color("highlight"))
        inactive_tab_bg = resolve_haze(get_tui_inactive_background())
        inactive_tab_fg = resolve_haze(get_neutral_color("muted"))

        tabs = self._build_tab_specs(tab_gap)
        self._click_regions = [(c, c + w, tid) for c, w, _, _, tid in tabs]
        entity_z_scan = engine.get_entity_z_levels("header") if engine else []
        rows = [
            self._render_tab_row(
                y_offset,
                width,
                tabs,
                engine,
                entity_z_scan,
                sky_fallback,
                pane_bg,
                pipe_color,
                active_tab_bg,
                active_tab_fg,
                inactive_tab_bg,
                inactive_tab_fg,
                Z60,
                Z70,
                Z80,
            )
            for y_offset in range(num_rows)
        ]
        return Group(*rows)

    def _build_tab_specs(self, tab_gap: int) -> list[tuple[int, int, str, bool, str]]:
        tabs: list[tuple[int, int, str, bool, str]] = []
        col = 1
        for tab_id, label in self.TABS:
            padded = f" {label} "
            width = len(padded)
            tabs.append((col, width, padded, self.active_tab == tab_id, tab_id))
            col += width + tab_gap
        return tabs

    def _tab_cell(
        self,
        x: int,
        y_offset: int,
        tabs: list[tuple[int, int, str, bool, str]],
        active_tab_bg: str,
        active_tab_fg: str,
        inactive_tab_bg: str,
        inactive_tab_fg: str,
    ) -> tuple[str, bool, bool, str | None, str | None]:
        for col, width, label, is_active, _tab_id in tabs:
            if col <= x < col + width:
                tab_bg = active_tab_bg if is_active else inactive_tab_bg
                tab_fg = active_tab_fg if is_active else inactive_tab_fg
                char = label[x - col] if y_offset == 1 else " "
                return char, True, is_active, tab_bg, tab_fg
        return " ", False, False, None, None

    def _sky_color(self, engine: AnimationEngine | None, x: int, global_y: int, sky_fallback: str) -> str:
        from teleclaude.cli.tui.animations.base import Z0

        sky_color = engine.get_layer_color(Z0, x, global_y, target="header") if engine else None
        return sky_color if isinstance(sky_color, str) else sky_fallback

    def _render_tab_row(
        self,
        y_offset: int,
        width: int,
        tabs: list[tuple[int, int, str, bool, str]],
        engine: AnimationEngine | None,
        entity_z_scan: list[int],
        sky_fallback: str,
        pane_bg: str,
        pipe_color: str,
        active_tab_bg: str,
        active_tab_fg: str,
        inactive_tab_bg: str,
        inactive_tab_fg: str,
        z60: int,
        z70: int,
        z80: int,
    ) -> Text:
        row_text = Text()
        global_y = 7 + y_offset
        for x in range(width):
            cell = self._tab_cell(x, y_offset, tabs, active_tab_bg, active_tab_fg, inactive_tab_bg, inactive_tab_fg)
            sky_color = self._sky_color(engine, x, global_y, sky_fallback)
            if y_offset == 2:
                self._append_transition_row(
                    row_text, x, global_y, cell, engine, entity_z_scan, sky_color, pane_bg, z70, z80
                )
            elif y_offset == 0:
                self._append_sky_row(row_text, x, global_y, engine, entity_z_scan, sky_color, pipe_color)
            else:
                self._append_label_row(row_text, x, global_y, cell, engine, entity_z_scan, sky_color, z60, z80)
        return row_text

    def _append_transition_row(
        self,
        row_text: Text,
        x: int,
        global_y: int,
        cell: tuple[str, bool, bool, str | None, str | None],
        engine: AnimationEngine | None,
        entity_z_scan: list[int],
        sky_color: str,
        pane_bg: str,
        z70: int,
        z80: int,
    ) -> None:
        _char, in_tab, active_tab_under, tab_bg, _tab_fg = cell
        top_half = (
            tab_bg or pane_bg
            if in_tab
            else blend_colors(self._sky_color(engine, x, global_y - 1, sky_color), "#ffffff", 0.05)
        )
        if engine:
            hit = _scan_entity_at(engine, entity_z_scan, x, global_y, z80 if active_tab_under else z70, pane_bg)
            if hit:
                e_char, e_fg, e_bg = hit
                if e_char is not None:
                    row_text.append(e_char, style=Style(color=_to_color(e_fg), bgcolor=_to_color(e_bg or pane_bg)))
                    return
                if e_bg is not None:
                    top_half = e_bg
        row_text.append("\u2580", style=Style(color=_to_color(top_half), bgcolor=_to_color(pane_bg)))

    def _append_sky_row(
        self,
        row_text: Text,
        x: int,
        global_y: int,
        engine: AnimationEngine | None,
        entity_z_scan: list[int],
        sky_color: str,
        pipe_color: str,
    ) -> None:
        final_bg = sky_color
        is_pipe = x in {13, 70}
        fg_char = "\u2551" if is_pipe else " "
        fg_color: str | None = pipe_color if is_pipe else None
        if engine:
            hit = _scan_entity_at(engine, entity_z_scan, x, global_y, 0, sky_color)
            if hit:
                e_char, e_fg, e_bg = hit
                if e_char is not None:
                    fg_char = e_char
                    fg_color = e_fg
                if e_bg is not None:
                    final_bg = e_bg
            if engine.has_active_animation and engine.is_external_light():
                color = engine.get_color(x, global_y)
                if color:
                    final_bg = blend_colors(final_bg, str(color), 0.1)
        row_text.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(final_bg)))

    def _append_label_row(
        self,
        row_text: Text,
        x: int,
        global_y: int,
        cell: tuple[str, bool, bool, str | None, str | None],
        engine: AnimationEngine | None,
        entity_z_scan: list[int],
        sky_color: str,
        z60: int,
        z80: int,
    ) -> None:
        char, in_tab, active_tab_under, tab_bg, tab_fg = cell
        final_bg = (tab_bg or sky_color) if in_tab else sky_color
        fg_char = char
        fg_color = None
        if engine:
            hit = _scan_entity_at(
                engine,
                entity_z_scan,
                x,
                global_y,
                z80 if in_tab and active_tab_under else (z60 if in_tab else 0),
                final_bg,
            )
            if hit:
                e_char, e_fg, e_bg = hit
                if e_char is not None:
                    fg_char = e_char
                    fg_color = e_fg
                if e_bg is not None:
                    final_bg = e_bg
            if not in_tab and engine.has_active_animation and engine.is_external_light():
                color = engine.get_color(x, global_y)
                if color:
                    final_bg = blend_colors(final_bg, str(color), 0.1)
        if not fg_color:
            fg_color = tab_fg if in_tab else resolve_haze(get_neutral_color("muted"))
        row_text.append(fg_char, style=Style(color=_to_color(fg_color), bgcolor=_to_color(final_bg)))

    def on_click(self, event: object) -> None:
        """Handle mouse click to switch tabs."""
        x = getattr(event, "x", -1)
        for col_start, col_end, tab_id in self._click_regions:
            if col_start <= x < col_end:
                self.post_message(self.TabClicked(tab_id))
                break

    def watch_active_tab(self, _value: str) -> None:
        self.refresh()
