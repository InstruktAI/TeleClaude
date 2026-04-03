"""Shared header scene projection for animated TUI widgets."""

# pylint: disable=duplicate-code  # Shares projection logic with banner/tab widgets by design.

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group
from rich.text import Text

from teleclaude.cli.tui.animation_engine import AnimationEngine
from teleclaude.cli.tui.animations.base import Z0
from teleclaude.cli.tui.theme import is_dark_mode
from teleclaude.cli.tui.widgets.banner import BANNER_LINES, Banner
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar

_HEADER_HEIGHT = len(BANNER_LINES) + 1 + 3


@dataclass(frozen=True)
class HeaderSceneFrame:
    """Projected shared ``header`` scene for Banner and BoxTabBar.

    This caches the raw animated header layers once per tick so downstream
    widgets can apply their own overlay logic without duplicating engine reads.
    """

    width: int
    dark_mode: bool
    sky_fallback: str
    layers_by_cell: dict[tuple[int, int], tuple[tuple[int, str], ...]]
    sky_by_cell: dict[tuple[int, int], str]

    def sky_background(self, x: int, y: int) -> str:
        """Return the projected sky background color at a header coordinate."""
        return self.sky_by_cell.get((x, y), self.sky_fallback)

    def scan_sky_entity(
        self,
        x: int,
        y: int,
        *,
        z_min: int = 0,
    ) -> tuple[str, str | None, str | None]:
        """Resolve banner-style entity composition at a header coordinate."""
        state: dict[str, str | bool | None] = {
            "fg_char": " ",
            "fg_color": None,
            "bg_entity_color": None,
            "need_behind": False,
        }

        for z, val in self.layers_by_cell.get((x, y), ()):
            if z <= z_min:
                break
            if _consume_sky_entity_value(state, val, z, self.dark_mode):
                break

        if state["need_behind"] and state["fg_color"] is None:
            state["fg_color"] = self.sky_background(x, y)

        return (
            str(state["fg_char"]),
            state["fg_color"] if isinstance(state["fg_color"], str) else None,
            state["bg_entity_color"] if isinstance(state["bg_entity_color"], str) else None,
        )

    # pylint: disable=too-many-return-statements,too-many-branches
    def scan_tab_entity(
        self,
        x: int,
        y: int,
        *,
        z_min: int,
        scene_bg: str,
    ) -> tuple[str | None, str | None, str | None] | None:
        """Resolve tab-bar entity composition at a header coordinate."""
        pending: tuple[str, str] | None = None
        for z, val in self.layers_by_cell.get((x, y), ()):
            if z <= z_min:
                break
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

    # pylint: enable=too-many-return-statements,too-many-branches


def build_header_scene_frame(
    *,
    engine: AnimationEngine | None,
    width: int,
) -> HeaderSceneFrame:
    """Project the shared ``header`` animation target once for the current frame."""
    dark = is_dark_mode()
    sky_fallback = "#000000" if dark else "#C8E8F8"
    layers_by_cell: dict[tuple[int, int], tuple[tuple[int, str], ...]] = {}
    sky_by_cell: dict[tuple[int, int], str] = {}

    if engine is None:
        return HeaderSceneFrame(width, dark, sky_fallback, layers_by_cell, sky_by_cell)

    z_levels = engine.get_entity_z_levels("header")
    for y in range(_HEADER_HEIGHT):
        for x in range(width):
            sky_val = engine.get_layer_color(Z0, x, y, target="header")
            sky_by_cell[(x, y)] = sky_val if isinstance(sky_val, str) else sky_fallback
            layers: list[tuple[int, str]] = []
            for z in z_levels:
                val = engine.get_layer_color(z, x, y, target="header")
                if isinstance(val, str):
                    layers.append((z, val))
            if layers:
                layers_by_cell[(x, y)] = tuple(layers)

    return HeaderSceneFrame(width, dark, sky_fallback, layers_by_cell, sky_by_cell)


def build_header_frames(*, banner: Banner, tab_bar: BoxTabBar) -> tuple[Text, Group]:
    """Build current banner and tab-bar renderables once for the current frame."""
    width = max(banner.size.width or 0, tab_bar.size.width or 80, 80)
    scene = build_header_scene_frame(engine=banner.animation_engine, width=width)
    banner_render = banner.build_render_frame(scene=scene)
    tab_render = tab_bar.build_render_frame(scene=scene)
    return banner_render, tab_render


def _consume_sky_entity_value(  # pylint: disable=too-many-return-statements
    state: dict[str, str | bool | None], val: str, z: int, dark_mode: bool
) -> bool:
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


def _entity_color(_ch: str, _z: int, _dark_mode: bool) -> str:
    return "#FFFFFF"
