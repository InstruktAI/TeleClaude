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

logger = get_logger(__name__)
from teleclaude.cli.tui.theme import (
    CONNECTOR_COLOR,
    NEUTRAL_HIGHLIGHT_COLOR,
    NEUTRAL_MUTED_COLOR,
    apply_tui_haze,
    blend_colors,
    is_dark_mode,
)

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_engine import AnimationEngine


def _to_color(c: str | int | None) -> str | None:
    """Helper to ensure Style receives a valid color string or None."""
    if isinstance(c, str) and len(c) > 1:
        return c
    return None


class BoxTabBar(TelecMixin, Widget):
    """3-row tab bar with box-drawing characters.
    Integrated with the Layered Animation Engine for physical occlusion.
    """

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
        from teleclaude.cli.tui.animations.base import (
            Z_SKY,
            Z_TABS_INACTIVE,
            Z_FOREGROUND,
            Z_TABS_ACTIVE,
        )

        # Calculate tab positions (1-char sky gap between tabs in light mode)
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
        for y_offset in range(3):
            row_text = Text()
            global_y = 7 + y_offset # Tabs start at Y=7
            
            for x in range(width):
                char = " "
                z_base = Z_TABS_INACTIVE
                
                # Check if x belongs to a tab
                in_tab = False
                active_tab_under = False
                for c, w, label, is_active, _ in tabs:
                    if c <= x < c + w + 2:
                        in_tab = True
                        if is_active: active_tab_under = True
                        
                        rel_x = x - c
                        if y_offset == 0:
                            if dark_mode:
                                if rel_x == 0: char = "\u256d"
                                elif rel_x == w + 1: char = "\u256e"
                                else: char = "\u2500"
                            # else: space (no top border in light mode)
                        elif y_offset == 1:
                            if rel_x == 0 or rel_x == w + 1:
                                char = "\u2502" if dark_mode else " "
                            elif 1 <= rel_x <= w: char = label[rel_x-1]
                        elif y_offset == 2:
                            if rel_x == 0 or rel_x == w + 1:
                                char = "\u2534" if dark_mode else " "
                            else: char = " " if (is_active or not dark_mode) else "\u2500"
                        break

                if not in_tab and y_offset == 2:
                    char = "\u2500" if dark_mode else " "  # Connector line (dark only)
                
                z_base = Z_TABS_ACTIVE if active_tab_under else Z_TABS_INACTIVE
                fg = NEUTRAL_HIGHLIGHT_COLOR if active_tab_under else NEUTRAL_MUTED_COLOR
                if not getattr(self.app, "app_focus", True):
                    fg = apply_tui_haze(fg)

                # 2. Get Background Atmosphere (Sky Z-0) from full width header
                sky_fallback = "#000000" if dark_mode else "#C8E8F8"
                bg_color = engine.get_layer_color(Z_SKY, x, global_y, target="header") if engine else None
                if not isinstance(bg_color, str): bg_color = sky_fallback

                # 3. Layered Compositing (Physical Occlusion)
                final_fg = fg
                final_bg = bg_color
                # All 3 rows of a tab box use TUI pane background; sky fills gaps between tabs
                if in_tab:
                    from teleclaude.cli.tui.theme import get_terminal_background
                    final_bg = get_terminal_background()
                fg_char = char
                fg_color = None
                
                if engine:
                    # Check for foreground entities (Z-7) from header
                    entity = engine.get_layer_color(Z_FOREGROUND, x, global_y, target="header")
                    
                    if Z_FOREGROUND > z_base:
                        if entity and entity != -1:
                            # PHYSICAL MASKING: Only show in non-physical space (not in tab or on line)
                            if not in_tab and not (not in_tab and y_offset == 2):
                                if isinstance(entity, str) and len(entity) == 1:
                                    fg_char = entity
                                    fg_color = "#FFFFFF"
                                elif isinstance(entity, str):
                                    fg_color = entity
                    
                    # Atmospheric light reflection (External) — skip for tab panes
                    if not in_tab and engine.has_active_animation and engine.is_external_light():
                        color = engine.get_color(x, global_y)
                        if color and color != -1:
                            color_str = str(color)
                            final_bg = blend_colors(str(final_bg), color_str, 0.1)
                            final_fg = blend_colors(str(final_fg), color_str, 0.5)

                row_text.append(fg_char, style=Style(color=_to_color(fg_color or final_fg), bgcolor=_to_color(final_bg)))
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
