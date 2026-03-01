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
    NEUTRAL_HIGHLIGHT_COLOR,
    NEUTRAL_MUTED_COLOR,
    apply_tui_haze,
    blend_colors,
    get_terminal_background,
    get_tui_inactive_background,
    is_dark_mode,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_engine import AnimationEngine


def _to_color(c: str | int | None) -> str | None:
    """Helper to ensure Style receives a valid color string or None."""
    if isinstance(c, str) and len(c) > 1:
        return c
    return None


class BoxTabBar(TelecMixin, Widget):
    """Tab bar. Dark mode: 3-row box-drawing. Light mode: 2-row half-block."""

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
        if not is_dark_mode():
            self.styles.height = 2

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
        focused = getattr(self.app, "app_focus", True)
        from teleclaude.cli.tui.animations.base import (
            Z_FOREGROUND,
            Z_SKY,
            Z_TABS_ACTIVE,
            Z_TABS_INACTIVE,
        )

        sky_fallback = "#000000" if dark_mode else "#C8E8F8"

        # Tab backgrounds: active vs inactive
        if dark_mode:
            from teleclaude.cli.tui.theme import get_billboard_background

            active_bg = get_billboard_background(focused)
            inactive_bg = get_billboard_background(False)
        else:
            active_bg = get_terminal_background()
            inactive_bg = get_tui_inactive_background()

        # Dark mode: 3 rows (box-drawing), 2-char gap (borders touch)
        # Light mode: 2 rows (▀ half-block + label), 3-char gap (1-char sky between tabs)
        num_rows = 3 if dark_mode else 2
        tab_gap = 2 if dark_mode else 3

        tabs: list[tuple[int, int, str, bool, str]] = []
        col = 1
        for tab_id, label in self.TABS:
            is_active = self.active_tab == tab_id
            padded = f" {label} "
            w = len(padded)
            tabs.append((col, w, padded, is_active, tab_id))
            col += w + tab_gap

        self._click_regions = [(c, c + w + 2, tid) for c, w, _, _, tid in tabs]

        rows = []
        for y_offset in range(num_rows):
            row_text = Text()
            global_y = 7 + y_offset  # Tab bar starts at Y=7

            for x in range(width):
                char = " "
                in_tab = False
                active_tab_under = False
                tab_bg: str | None = None

                for c, w, label, is_active, _ in tabs:
                    if c <= x < c + w + 2:
                        in_tab = True
                        active_tab_under = is_active
                        tab_bg = active_bg if is_active else inactive_bg
                        rel_x = x - c

                        if dark_mode:
                            if y_offset == 0:
                                if rel_x == 0:
                                    char = "\u256d"  # ╭
                                elif rel_x == w + 1:
                                    char = "\u256e"  # ╮
                                else:
                                    char = "\u2500"  # ─
                            elif y_offset == 1:
                                if rel_x == 0 or rel_x == w + 1:
                                    char = "\u2502"  # │
                                elif 1 <= rel_x <= w:
                                    char = label[rel_x - 1]
                            elif y_offset == 2:
                                if rel_x == 0 or rel_x == w + 1:
                                    char = "\u2534"  # ┴
                                else:
                                    char = " " if is_active else "\u2500"
                        else:
                            # Light mode
                            if y_offset == 0:
                                char = "\u2580"  # ▀ — fg=sky (top), bg=tab (bottom)
                            elif y_offset == 1:
                                if rel_x == 0 or rel_x == w + 1:
                                    char = " "
                                elif 1 <= rel_x <= w:
                                    char = label[rel_x - 1]
                        break

                if dark_mode and not in_tab and y_offset == 2:
                    char = "\u2500"  # ─ connector line between tabs

                # Sky color at this position
                sky_color = engine.get_layer_color(Z_SKY, x, global_y, target="header") if engine else None
                if not isinstance(sky_color, str):
                    sky_color = sky_fallback

                z_base = Z_TABS_ACTIVE if active_tab_under else Z_TABS_INACTIVE
                fg_text = NEUTRAL_HIGHLIGHT_COLOR if active_tab_under else NEUTRAL_MUTED_COLOR
                if not focused:
                    fg_text = apply_tui_haze(fg_text)

                # Light mode row 0: ▀ half-block — fg=sky fills top, bg=tab fills bottom
                if not dark_mode and in_tab and y_offset == 0:
                    row_text.append(
                        char,
                        style=Style(color=_to_color(sky_color), bgcolor=_to_color(tab_bg)),
                    )
                    continue

                # All other positions
                final_bg: str = (tab_bg or sky_color) if in_tab else sky_color
                fg_char = char
                fg_color: str | None = None

                if engine:
                    entity = engine.get_layer_color(Z_FOREGROUND, x, global_y, target="header")
                    if Z_FOREGROUND > z_base and entity and entity != -1:
                        if not in_tab:
                            if isinstance(entity, str) and len(entity) == 1:
                                fg_char = entity
                                fg_color = "#FFFFFF"
                            elif isinstance(entity, str):
                                fg_color = entity

                    if not in_tab and engine.has_active_animation and engine.is_external_light():
                        color = engine.get_color(x, global_y)
                        if color:
                            color_str = str(color)
                            final_bg = blend_colors(final_bg, color_str, 0.1)
                            fg_text = blend_colors(fg_text, color_str, 0.5)

                row_text.append(
                    fg_char,
                    style=Style(color=_to_color(fg_color or fg_text), bgcolor=_to_color(final_bg)),
                )
            rows.append(row_text)

        return Group(*rows)

    def on_click(self, event: object) -> None:
        """Handle mouse click to switch tabs."""
        x = getattr(event, "x", -1)
        for col_start, col_end, tab_id in self._click_regions:
            if col_start <= x < col_end:
                self.post_message(self.TabClicked(tab_id))
                break

    def watch_active_tab(self, _value: str) -> None:
        self.refresh()
