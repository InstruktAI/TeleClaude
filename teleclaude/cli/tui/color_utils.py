"""Shared color utilities for TUI.

All color consumers import from here. No duplication across theme.py / animation_colors.py.
"""

from __future__ import annotations

import colorsys
import re

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert #RRGGBB hex string to (r, g, b) integer tuple."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert (r, g, b) integers to #RRGGBB string (clamped to 0-255)."""
    r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def is_hex_color(value: str) -> bool:
    """Return True if value is a valid #RRGGBB hex color."""
    return bool(_HEX_COLOR_RE.match(value or ""))


def blend(base: str, target: str, factor: float) -> str:
    """Blend two hex colors. result = base*(1-factor) + target*factor."""
    b_hex = str(base)
    t_hex = str(target)
    if not is_hex_color(b_hex) or not is_hex_color(t_hex):
        return b_hex
    br, bg, bb = hex_to_rgb(b_hex)
    tr, tg, tb = hex_to_rgb(t_hex)
    return rgb_to_hex(
        int(br * (1 - factor) + tr * factor),
        int(bg * (1 - factor) + tg * factor),
        int(bb * (1 - factor) + tb * factor),
    )


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of a hex color."""
    r8, g8, b8 = hex_to_rgb(hex_color)

    def _srgb_to_linear(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _srgb_to_linear(r8) + 0.7152 * _srgb_to_linear(g8) + 0.0722 * _srgb_to_linear(b8)


def hex_to_nearest_xterm256(hex_color: str) -> int:
    """Convert a hex color to the nearest xterm256 color code.

    Used exclusively by the tmux output path (pane_manager) which requires
    integer color codes for terminal escape sequences.
    """
    r, g, b = hex_to_rgb(hex_color)

    # Check grayscale ramp (232-255) first
    best_gray_dist = float("inf")
    best_gray = 232
    for i in range(24):
        val = i * 10 + 8
        dist = (r - val) ** 2 + (g - val) ** 2 + (b - val) ** 2
        if dist < best_gray_dist:
            best_gray_dist = dist
            best_gray = 232 + i

    # Check 6x6x6 color cube (16-231)
    def _nearest_cube_component(v: int) -> int:
        if v < 48:
            return 0
        return min(5, (v - 35) // 40)

    ri = _nearest_cube_component(r)
    gi = _nearest_cube_component(g)
    bi = _nearest_cube_component(b)
    cube_code = 16 + 36 * ri + 6 * gi + bi
    cr = 0 if ri == 0 else ri * 40 + 55
    cg = 0 if gi == 0 else gi * 40 + 55
    cb = 0 if bi == 0 else bi * 40 + 55
    cube_dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2

    return best_gray if best_gray_dist < cube_dist else cube_code


def deepen_for_light_mode(color_hex: str) -> str:
    """15% brightness reduction with minimum floor for light mode neon visibility."""
    if not is_hex_color(color_hex):
        return color_hex
    r, g, b = hex_to_rgb(color_hex)
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    v = max(0.60, v * 0.85)
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    return rgb_to_hex(int(nr * 255), int(ng * 255), int(nb * 255))


def letter_color_floor(color_hex: str, floor_hex: str) -> str:
    """Clamp each RGB channel to at least the floor color.

    Prevents animation colors on letter pixels from appearing darker than the
    letter's resting base gray.
    """
    if not is_hex_color(color_hex) or not is_hex_color(floor_hex):
        return color_hex
    cr, cg, cb = hex_to_rgb(color_hex)
    fr, fg, fb = hex_to_rgb(floor_hex)
    return rgb_to_hex(max(cr, fr), max(cg, fg), max(cb, fb))
