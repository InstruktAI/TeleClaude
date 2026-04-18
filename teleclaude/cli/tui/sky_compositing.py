"""Shared sky entity compositing functions for header and banner rendering."""

from __future__ import annotations


def consume_sky_entity_value(state: dict[str, str | bool | None], val: str, z: int, dark_mode: bool) -> bool:
    """Parse a sky entity value and apply it to the rendering state."""
    vlen = len(val)
    if vlen == 15 and val[0] == "#" and val[7] == "#":
        return apply_sky_entity(state, val[14], val[0:7], val[7:14], partial=False)
    if vlen == 8 and val[0] == "#":
        return apply_sky_entity(state, val[7], val[:7], val[:7], partial=False)
    if vlen == 9 and val[0] == "\x01" and val[1] == "#":
        return apply_sky_entity(state, val[8], val[1:8], val[1:8], partial=val[8] != "\u2588")
    if vlen == 1:
        color = _entity_color(val, z, dark_mode)
        return apply_sky_entity(state, val, color, color, partial=False)
    if vlen == 2 and val[0] == "\x01":
        ch = val[1]
        color = _entity_color(ch, z, dark_mode)
        return apply_sky_entity(state, ch, color, color, partial=ch != "\u2588")
    if vlen == 7 and val[0] == "#":
        return apply_sky_ambient(state, val)
    return False


def apply_sky_entity(
    state: dict[str, str | bool | None],
    ch: str,
    fg_color: str,
    bg_color: str,
    *,
    partial: bool,
) -> bool:
    """Apply an entity (character + colors) to the rendering state."""
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


def apply_sky_ambient(state: dict[str, str | bool | None], color: str) -> bool:
    """Apply ambient sky background color to the rendering state."""
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
