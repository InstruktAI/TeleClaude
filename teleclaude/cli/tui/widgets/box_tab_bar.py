"""Box-drawing tab bar matching old curses TUI style."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, NEUTRAL_HIGHLIGHT_COLOR, NEUTRAL_MUTED_COLOR


from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import (
    CONNECTOR_COLOR,
    NEUTRAL_HIGHLIGHT_COLOR,
    NEUTRAL_MUTED_COLOR,
    apply_tui_haze,
    blend_colors,
)

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_engine import AnimationEngine


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

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.animation_engine: AnimationEngine | None = None
        self._click_regions: list[tuple[int, int, str]] = []

    def render(self) -> Group:
        width = self.size.width or 80
        line_color = CONNECTOR_COLOR
        engine = self.animation_engine
        from teleclaude.cli.tui.animations.base import (
            Z_SKY,
            Z_TABS_INACTIVE,
            Z_FOREGROUND,
            Z_TABS_ACTIVE,
        )

        # Calculate tab positions
        tabs: list[tuple[int, int, str, bool, str]] = []
        col = 1
        for tab_id, label in self.TABS:
            is_active = self.active_tab == tab_id
            padded = f" {label} "
            w = len(padded)
            tabs.append((col, w, padded, is_active, tab_id))
            col += w + 2

        self._click_regions = [(c, c + w + 2, tid) for c, w, _, _, tid in tabs]

        rows = []
        for y_offset in range(3):
            row_text = Text()
            global_y = 7 + y_offset # Tabs start at Y=7
            
            for x in range(width):
                # 1. Determine physical character and its base Z-layer
                char = " "
                z_base = Z_TABS_INACTIVE
                base_style = NEUTRAL_MUTED_COLOR
                
                # Check if x,y belongs to a tab
                in_tab = False
                active_tab_under = False
                for c, w, label, is_active, _ in tabs:
                    if c <= x < c + w + 2:
                        in_tab = True
                        if is_active: active_tab_under = True
                        
                        # Character selection based on position in tab
                        rel_x = x - c
                        if y_offset == 0:
                            if rel_x == 0: char = "\u256d"
                            elif rel_x == w + 1: char = "\u256e"
                            else: char = "\u2500"
                        elif y_offset == 1:
                            if rel_x == 0 or rel_x == w + 1: char = "\u2502"
                            elif 1 <= rel_x <= w: char = label[rel_x-1]
                        elif y_offset == 2:
                            if rel_x == 0 or rel_x == w + 1: char = "\u2534"
                            else: char = " " if is_active else "\u2500"
                        break
                
                if not in_tab and y_offset == 2:
                    char = "\u2500" # Bottom connector line
                
                z_base = Z_TABS_ACTIVE if active_tab_under else Z_TABS_INACTIVE
                fg = NEUTRAL_HIGHLIGHT_COLOR if active_tab_under else NEUTRAL_MUTED_COLOR
                if not getattr(self.app, "app_focus", True):
                    fg = apply_tui_haze(fg)

                # 2. Get Background Atmosphere (Sky Z-0)
                bg_color = engine.get_layer_color(Z_SKY, x, global_y) if engine else None
                if not isinstance(bg_color, str): bg_color = "#000000"

                # 3. Layered Compositing (Physical Occlusion)
                # Front-most layers can overwrite or reflect
                final_fg = fg
                final_bg = bg_color
                
                if engine:
                    # Check for foreground entities (Z-7) - e.g. The Car
                    entity = engine.get_layer_color(Z_FOREGROUND, x, global_y)
                    
                    # Occlusion logic:
                    # If Z_FOREGROUND (7) > z_base (5 for inactive, 10 for active)
                    if Z_FOREGROUND > z_base:
                        if entity and entity != -1:
                            if isinstance(entity, str) and len(entity) == 1:
                                char = entity
                                final_fg = "#FFFFFF"
                            elif isinstance(entity, str):
                                final_fg = entity
                    
                    # Atmospheric light reflection (External)
                    if engine.has_active_animation and engine.is_external_light():
                        color = engine.get_color(x, global_y)
                        if color and color != -1:
                            # Reflect light on the tab background
                            blend_pct = 0.3 if in_tab else 0.1
                            final_bg = blend_colors(final_bg, color, blend_pct)
                            # Also tint the foreground slightly
                            final_fg = blend_colors(final_fg, color, 0.5)

                row_text.append(char, style=Style(color=final_fg, bgcolor=final_bg))
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
