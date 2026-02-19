"""Agent colors and styling for TUI.

Dual-audience module:
- Tmux pane manager: xterm256 codes and hex colors for terminal escape sequences
- Textual widgets: Rich Style objects and CSS-compatible color definitions

Detects macOS dark/light mode via system settings.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Optional

from rich.style import Style

from teleclaude.config import config

# --- Theme Mode Detection ---

_APPLE_DARK_LABEL = "Dark"


class ThemeMode:
    DARK = "dark"
    LIGHT = "light"


def _get_tmux_socket_path() -> Optional[str]:
    tmux_env = os.environ.get("TMUX")
    if not tmux_env:
        return None
    return tmux_env.split(",", 1)[0] or None


def _get_tmux_appearance_mode() -> Optional[str]:
    tmux_bin = config.computer.tmux_binary
    socket_path = _get_tmux_socket_path()
    cmd = [tmux_bin]
    if socket_path:
        cmd.extend(["-S", socket_path])
    cmd.extend(["show", "-gv", "@appearance_mode"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    mode = (result.stdout or "").strip().lower()
    if mode in {ThemeMode.DARK, ThemeMode.LIGHT}:
        return mode
    return None


def _get_env_appearance_mode() -> Optional[str]:
    mode = (os.environ.get("APPEARANCE_MODE") or "").strip().lower()
    if mode in {ThemeMode.DARK, ThemeMode.LIGHT}:
        return mode
    return None


def _get_system_appearance_mode() -> Optional[str]:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip().lower()
    if _APPLE_DARK_LABEL in stdout:
        return ThemeMode.DARK
    if result.returncode != 0:
        if "does not exist" in stderr or "could not be found" in stderr:
            return ThemeMode.LIGHT
        return None
    return ThemeMode.LIGHT


def get_system_dark_mode() -> bool | None:
    mode = _get_system_appearance_mode()
    if mode is None:
        return None
    return mode == ThemeMode.DARK


def is_dark_mode() -> bool:
    """Resolve dark mode with stable precedence.

    1) APPEARANCE_MODE env  2) Host system  3) tmux  4) dark default
    """
    env_mode = _get_env_appearance_mode()
    if env_mode:
        return env_mode == ThemeMode.DARK
    system_mode = _get_system_appearance_mode()
    if system_mode:
        return system_mode == ThemeMode.DARK
    if sys.platform == "darwin":
        cached = globals().get("_is_dark_mode")
        if isinstance(cached, bool):
            return cached
        return True
    tmux_mode = _get_tmux_appearance_mode()
    if tmux_mode:
        return tmux_mode == ThemeMode.DARK
    return True


_is_dark_mode: bool = is_dark_mode()


def get_current_mode() -> bool:
    """Return True if dark mode."""
    return _is_dark_mode


def refresh_mode() -> None:
    """Re-probe system appearance and update cached mode."""
    global _is_dark_mode, _terminal_bg_cache  # noqa: PLW0603
    _is_dark_mode = is_dark_mode()
    _terminal_bg_cache = None


# --- Agent xterm256 Color Codes ---
# Used by pane_manager for tmux foreground and external references.

_DEFAULT_AGENT = "codex"

_AGENT_SUBTLE_DARK = {"claude": 94, "gemini": 103, "codex": 67}
_AGENT_SUBTLE_LIGHT = {"claude": 180, "gemini": 177, "codex": 110}

_AGENT_MUTED_DARK = {"claude": 137, "gemini": 141, "codex": 110}
_AGENT_MUTED_LIGHT = {"claude": 137, "gemini": 135, "codex": 67}

_AGENT_NORMAL_DARK = {"claude": 180, "gemini": 183, "codex": 153}
_AGENT_NORMAL_LIGHT = {"claude": 94, "gemini": 90, "codex": 24}

_AGENT_HIGHLIGHT_DARK = {"claude": 231, "gemini": 231, "codex": 231}
_AGENT_HIGHLIGHT_LIGHT = {"claude": 16, "gemini": 16, "codex": 16}


def _safe_agent(agent: str) -> str:
    """Normalize unknown agent names to a stable default."""
    return agent if agent in ("claude", "gemini", "codex") else _DEFAULT_AGENT


def get_agent_normal_color(agent: str) -> int:
    """xterm256 code for agent's normal text color."""
    key = _safe_agent(agent)
    return _AGENT_NORMAL_DARK[key] if _is_dark_mode else _AGENT_NORMAL_LIGHT[key]


def get_agent_highlight_color(agent: str) -> int:
    """xterm256 code for agent's highlight color (maximum contrast)."""
    key = _safe_agent(agent)
    return _AGENT_HIGHLIGHT_DARK[key] if _is_dark_mode else _AGENT_HIGHLIGHT_LIGHT[key]


def get_agent_muted_color(agent: str) -> int:
    """xterm256 code for agent's muted text color."""
    key = _safe_agent(agent)
    return _AGENT_MUTED_DARK[key] if _is_dark_mode else _AGENT_MUTED_LIGHT[key]


def get_agent_subtle_color(agent: str) -> int:
    """xterm256 code for agent's subtle background tint."""
    key = _safe_agent(agent)
    return _AGENT_SUBTLE_DARK[key] if _is_dark_mode else _AGENT_SUBTLE_LIGHT[key]


# --- Agent Hex Colors (for tmux pane backgrounds) ---

_AGENT_HEX_COLORS_DARK: dict[str, str] = {
    "claude": "#af875f",
    "gemini": "#af87ff",
    "codex": "#87afaf",
}

_AGENT_HEX_COLORS_LIGHT: dict[str, str] = {
    "claude": "#af875f",
    "gemini": "#af5fff",
    "codex": "#5f8787",
}

_LIGHT_MODE_PAPER_BG = "#fdf6e3"

_AGENT_PANE_INACTIVE_HAZE_PERCENTAGE = 0.12 if not _is_dark_mode else 0.24
_AGENT_PANE_TREE_SELECTED_HAZE_PERCENTAGE = 0.04 if not _is_dark_mode else 0.08
_AGENT_PANE_ACTIVE_HAZE_PERCENTAGE = 0.0
_AGENT_STATUS_HAZE_PERCENTAGE = 0.06
_TUI_INACTIVE_HAZE_PERCENTAGE_LIGHT = 0.04
_TUI_INACTIVE_HAZE_PERCENTAGE_DARK = 0.08
_TERMINAL_HINT_WEIGHT = 0.35
_DARK_HINT_MAX_LUMINANCE = 0.45
_LIGHT_HINT_MIN_LUMINANCE = 0.55

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_terminal_bg_cache: str | None = None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _is_hex_color(value: str) -> bool:
    return bool(_HEX_COLOR_RE.match(value or ""))


def _relative_luminance(hex_color: str) -> float:
    r8, g8, b8 = _hex_to_rgb(hex_color)

    def _srgb_to_linear(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _srgb_to_linear(r8) + 0.7152 * _srgb_to_linear(g8) + 0.0722 * _srgb_to_linear(b8)


def _read_terminal_bg_from_appearance() -> str | None:
    appearance_bin = os.path.expanduser("~/.local/bin/appearance")
    if not os.path.exists(appearance_bin):
        return None
    try:
        result = subprocess.run([appearance_bin, "get-terminal-bg"], capture_output=True, text=True, timeout=1)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value if _is_hex_color(value) else None


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def blend_colors(base_hex: str, agent_hex: str, percentage: float) -> str:
    """Blend two hex colors. new = base*(1-pct) + agent*pct"""
    br, bg, bb = _hex_to_rgb(base_hex)
    ar, ag, ab = _hex_to_rgb(agent_hex)
    return _rgb_to_hex(
        int(br * (1 - percentage) + ar * percentage),
        int(bg * (1 - percentage) + ag * percentage),
        int(bb * (1 - percentage) + ab * percentage),
    )


def get_terminal_background() -> str:
    """Get terminal's background color (hex), with mode-safe baseline and hint blending."""
    global _terminal_bg_cache  # noqa: PLW0603
    if _terminal_bg_cache:
        return _terminal_bg_cache
    mode_default_bg = "#000000" if _is_dark_mode else _LIGHT_MODE_PAPER_BG
    hint = _read_terminal_bg_from_appearance()
    if hint:
        lum = _relative_luminance(hint)
        if _is_dark_mode and lum <= _DARK_HINT_MAX_LUMINANCE:
            _terminal_bg_cache = blend_colors(mode_default_bg, hint, _TERMINAL_HINT_WEIGHT)
            return _terminal_bg_cache
        elif not _is_dark_mode and lum >= _LIGHT_HINT_MIN_LUMINANCE:
            _terminal_bg_cache = blend_colors(mode_default_bg, hint, _TERMINAL_HINT_WEIGHT)
            return _terminal_bg_cache
    _terminal_bg_cache = mode_default_bg
    return _terminal_bg_cache


def get_tui_inactive_background() -> str:
    base_bg = get_terminal_background()
    blend_target = "#ffffff" if _is_dark_mode else "#000000"
    pct = _TUI_INACTIVE_HAZE_PERCENTAGE_DARK if _is_dark_mode else _TUI_INACTIVE_HAZE_PERCENTAGE_LIGHT
    return blend_colors(base_bg, blend_target, pct)


def get_agent_pane_inactive_background(agent: str, haze_percentage: float | None = None) -> str:
    colors = _AGENT_HEX_COLORS_DARK if _is_dark_mode else _AGENT_HEX_COLORS_LIGHT
    base_bg = get_terminal_background()
    agent_color = colors[_safe_agent(agent)]
    pct = _AGENT_PANE_INACTIVE_HAZE_PERCENTAGE if haze_percentage is None else haze_percentage
    return blend_colors(base_bg, agent_color, pct)


def get_agent_pane_selected_background(agent: str) -> str:
    return get_agent_pane_inactive_background(agent, haze_percentage=_AGENT_PANE_TREE_SELECTED_HAZE_PERCENTAGE)


def get_agent_pane_active_background(agent: str) -> str:
    return get_agent_pane_inactive_background(agent, haze_percentage=_AGENT_PANE_ACTIVE_HAZE_PERCENTAGE)


def get_agent_status_background(agent: str) -> str:
    colors = _AGENT_HEX_COLORS_DARK if _is_dark_mode else _AGENT_HEX_COLORS_LIGHT
    base_bg = get_terminal_background()
    return blend_colors(base_bg, colors[_safe_agent(agent)], _AGENT_STATUS_HAZE_PERCENTAGE)


# --- Pane Theming Mode ---

PANE_THEMING_MODE_FULL = "full"
PANE_THEMING_MODE_SEMI = "semi"
PANE_THEMING_MODE_OFF = "off"
PANE_THEMING_MODE_HIGHLIGHT = "highlight"
PANE_THEMING_MODE_HIGHLIGHT_EXT = "highlight2"
PANE_THEMING_MODE_AGENT = "agent"
PANE_THEMING_MODE_AGENT_PLUS = "agent_plus"

PANE_THEMING_MODE_CYCLE = (
    PANE_THEMING_MODE_OFF,
    PANE_THEMING_MODE_HIGHLIGHT,
    PANE_THEMING_MODE_HIGHLIGHT_EXT,
    PANE_THEMING_MODE_AGENT,
    PANE_THEMING_MODE_AGENT_PLUS,
)

_PANE_THEMING_MODE_CANONICAL: dict[str, str] = {
    PANE_THEMING_MODE_SEMI: PANE_THEMING_MODE_AGENT,
    PANE_THEMING_MODE_FULL: PANE_THEMING_MODE_AGENT_PLUS,
}

_PANE_THEMING_MODE_TO_LEVEL: dict[str, int] = {
    PANE_THEMING_MODE_OFF: 0,
    PANE_THEMING_MODE_HIGHLIGHT: 1,
    PANE_THEMING_MODE_HIGHLIGHT_EXT: 2,
    PANE_THEMING_MODE_AGENT: 3,
    PANE_THEMING_MODE_AGENT_PLUS: 4,
}

_PANE_LEVEL_TO_CANONICAL_MODE = (
    PANE_THEMING_MODE_OFF,
    PANE_THEMING_MODE_HIGHLIGHT,
    PANE_THEMING_MODE_HIGHLIGHT_EXT,
    PANE_THEMING_MODE_AGENT,
    PANE_THEMING_MODE_AGENT_PLUS,
)

_VALID_PANE_THEMING_MODES = set(_PANE_THEMING_MODE_TO_LEVEL)
_PANE_THEMING_MODE_OVERRIDE: str | None = None


def normalize_pane_theming_mode(mode: str) -> str:
    canonical = (mode or "").strip().lower()
    canonical = _PANE_THEMING_MODE_CANONICAL.get(canonical, canonical)
    if canonical not in _VALID_PANE_THEMING_MODES:
        raise ValueError(f"Invalid pane_theming_mode: {mode}")
    return canonical


def get_pane_theming_mode() -> str:
    if _PANE_THEMING_MODE_OVERRIDE:
        return _PANE_THEMING_MODE_OVERRIDE
    configured = str(config.ui.pane_theming_mode)  # type: ignore[attr-defined]
    try:
        return normalize_pane_theming_mode(configured)
    except ValueError:
        return PANE_THEMING_MODE_AGENT_PLUS


def get_pane_theming_mode_level(mode: str | None = None) -> int:
    canonical = normalize_pane_theming_mode(mode if mode is not None else get_pane_theming_mode())
    return _PANE_THEMING_MODE_TO_LEVEL[canonical]


def should_apply_session_theming(level: int | None = None) -> bool:
    pane_level = get_pane_theming_mode_level() if level is None else level
    return pane_level in (1, 3, 4)


def should_apply_paint_pane_theming(level: int | None = None) -> bool:
    pane_level = get_pane_theming_mode_level() if level is None else level
    return pane_level == 3


def set_pane_theming_mode(mode: str | None) -> None:
    global _PANE_THEMING_MODE_OVERRIDE  # noqa: PLW0603
    if not mode:
        _PANE_THEMING_MODE_OVERRIDE = None  # type: ignore[reportConstantRedefinition]
        return
    _PANE_THEMING_MODE_OVERRIDE = normalize_pane_theming_mode(mode)  # type: ignore[reportConstantRedefinition]


def get_pane_theming_mode_from_level(level: int) -> str:
    if level < 0 or level >= len(_PANE_LEVEL_TO_CANONICAL_MODE):
        raise ValueError(f"pane_theming_mode level must be 0..{len(_PANE_LEVEL_TO_CANONICAL_MODE) - 1}")
    return _PANE_LEVEL_TO_CANONICAL_MODE[level]


# --- Rich Style Definitions for Textual Widgets ---

# CSS-compatible color values per agent per tier.
# These map to the same xterm256 codes used for tmux panes.

_agent_rich_colors: dict[str, dict[str, str]] = {}


def _build_rich_colors() -> None:
    """Rebuild Rich color tables for current dark/light mode."""
    global _agent_rich_colors  # noqa: PLW0603
    if _is_dark_mode:
        _agent_rich_colors = {
            "claude": {
                "subtle": "color(94)",
                "muted": "color(137)",
                "normal": "color(180)",
                "highlight": "color(231)",
            },
            "gemini": {
                "subtle": "color(103)",
                "muted": "color(141)",
                "normal": "color(183)",
                "highlight": "color(231)",
            },
            "codex": {
                "subtle": "color(67)",
                "muted": "color(110)",
                "normal": "color(153)",
                "highlight": "color(231)",
            },
        }
    else:
        _agent_rich_colors = {
            "claude": {
                "subtle": "color(180)",
                "muted": "color(137)",
                "normal": "color(94)",
                "highlight": "color(16)",
            },
            "gemini": {
                "subtle": "color(177)",
                "muted": "color(135)",
                "normal": "color(90)",
                "highlight": "color(16)",
            },
            "codex": {
                "subtle": "color(110)",
                "muted": "color(67)",
                "normal": "color(24)",
                "highlight": "color(16)",
            },
        }


_build_rich_colors()

# Peaceful mode: neutral grays (no agent tint)
PEACEFUL_NORMAL_COLOR = "color(250)" if _is_dark_mode else "color(238)"
PEACEFUL_MUTED_COLOR = "color(240)" if _is_dark_mode else "color(244)"

# Banner muted color
BANNER_COLOR = "color(240)" if _is_dark_mode else "color(244)"

# Status/footer foreground
STATUS_FG_COLOR = "#727578"


def get_agent_style(agent: str, tier: str = "normal") -> Style:
    """Get a Rich Style for an agent at a given tier.

    Args:
        agent: "claude", "gemini", "codex"
        tier: "subtle", "muted", "normal", "highlight"
    """
    safe = _safe_agent(agent)
    color = _agent_rich_colors.get(safe, _agent_rich_colors[_DEFAULT_AGENT]).get(tier, "default")
    bold = tier == "highlight"
    return Style(color=color, bold=bold)


def get_agent_color(agent: str, tier: str = "normal") -> str:
    """Get the Rich color string for an agent at a given tier."""
    safe = _safe_agent(agent)
    return _agent_rich_colors.get(safe, _agent_rich_colors[_DEFAULT_AGENT]).get(tier, "default")


def get_agent_css_class(agent: str) -> str:
    """Get CSS class name for an agent."""
    return f"agent-{_safe_agent(agent)}"


# --- Compatibility layer for agent_status.py ---
# The build_agent_render_spec function uses this to determine colors.


def get_agent_status_style(agent: str, *, muted: bool) -> Style:
    """Get Rich Style for agent status display (footer/modal)."""
    tier = "muted" if muted else "normal"
    return get_agent_style(agent, tier)


# Keep old function signature for pane_manager compatibility
def get_agent_status_color_pair(agent: str, *, muted: bool) -> int:
    """Legacy: return xterm256 code for agent status.

    Used by agent_status.py build_agent_render_spec. Returns the raw xterm256
    color code instead of a curses pair ID.
    """
    safe = _safe_agent(agent)
    if muted:
        return _AGENT_MUTED_DARK[safe] if _is_dark_mode else _AGENT_MUTED_LIGHT[safe]
    return _AGENT_NORMAL_DARK[safe] if _is_dark_mode else _AGENT_NORMAL_LIGHT[safe]


# --- Legacy compatibility stubs (old curses widgets still import these) ---
# Delete these when Phase 4 cleanup removes old curses code.

AGENT_COLORS: dict[str, dict[str, int]] = {
    "claude": {"normal": 0, "highlight": 0, "muted": 0},
    "gemini": {"normal": 0, "highlight": 0, "muted": 0},
    "codex": {"normal": 0, "highlight": 0, "muted": 0},
}


def get_tab_line_attr() -> int:
    return 0


def get_layer_attr(_depth: int = 0) -> int:
    return 0


def get_selection_attr(_depth: int = 0) -> int:
    return 0


def get_modal_border_attr() -> int:
    return 0


def get_input_border_attr() -> int:
    return 0
