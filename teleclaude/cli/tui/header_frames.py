"""Shared header frame precomputation for animated TUI widgets."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text

from teleclaude.cli.tui.widgets.banner import Banner
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar


def build_header_frames(*, banner: Banner, tab_bar: BoxTabBar) -> tuple[Text, Group]:
    """Build current banner and tab-bar renderables once for the current frame.

    The animation engine already advances on a fixed cadence.  Precomputing the
    Rich renderables here lets the widgets serve cached frames during the
    subsequent Textual repaint cycle instead of recomputing their full animated
    projection on every render call.
    """

    banner_render = banner.build_render_frame()
    tab_render = tab_bar.build_render_frame()
    return banner_render, tab_render
