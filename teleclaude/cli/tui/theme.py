"""Agent colors and styling for TUI.

Single hex-based color palette as the source of truth. Everything derived from it.

Dual-audience module:
- Tmux pane manager: hex colors (converted to xterm256 only at the tmux boundary)
- Textual widgets: Rich Style objects and CSS-compatible hex color definitions

Detects macOS dark/light mode via system settings.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

from rich.style import Style
from textual.theme import Theme

from teleclaude.cli.tui.color_utils import (
    blend,
    deepen_for_light_mode,
    is_hex_color,
    letter_color_floor,
    relative_luminance,
)
from teleclaude.config import config

# Re-export color utilities that consumers import from theme
__all_reexports__ = [blend, deepen_for_light_mode, letter_color_floor]

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


def _detect_dark_mode() -> bool:
    """Probe system dark mode (spawns subprocesses — call sparingly).

    Precedence: 1) APPEARANCE_MODE env  2) Host system  3) tmux  4) dark default
    """
    env_mode = _get_env_appearance_mode()
    if env_mode:
        return env_mode == ThemeMode.DARK
    system_mode = _get_system_appearance_mode()
    if system_mode:
        return system_mode == ThemeMode.DARK
    tmux_mode = _get_tmux_appearance_mode()
    if tmux_mode:
        return tmux_mode == ThemeMode.DARK
    return True


_is_dark_mode: bool = _detect_dark_mode()


def is_dark_mode() -> bool:
    """Return cached dark mode state. Call refresh_mode() to re-probe."""
    return _is_dark_mode


def get_current_mode() -> bool:
    """Return True if dark mode."""
    return _is_dark_mode


def refresh_mode() -> None:
    """Re-probe system appearance and rebuild all mode-dependent color tables."""
    global _is_dark_mode, _terminal_bg_cache  # noqa: PLW0603
    _is_dark_mode = _detect_dark_mode()
    _terminal_bg_cache = None
    _build_rich_colors()


# =============================================================================
# THE PALETTE — every color consumer derives from this.
# =============================================================================

AGENT_PALETTE: dict[str, dict[str, dict[str, str]]] = {
    "dark": {
        "claude": {"subtle": "#875f00", "muted": "#af875f", "normal": "#d7af87", "highlight": "#ffffff"},
        "gemini": {"subtle": "#8787af", "muted": "#af87ff", "normal": "#d7afff", "highlight": "#ffffff"},
        "codex": {"subtle": "#5f87af", "muted": "#87afd7", "normal": "#afd7ff", "highlight": "#ffffff"},
    },
    "light": {
        "claude": {"subtle": "#d7af87", "muted": "#af875f", "normal": "#875f00", "highlight": "#000000"},
        "gemini": {"subtle": "#d787ff", "muted": "#af5fff", "normal": "#870087", "highlight": "#000000"},
        "codex": {"subtle": "#87afd7", "muted": "#5f87af", "normal": "#005f87", "highlight": "#000000"},
    },
}

STRUCTURAL_PALETTE: dict[str, dict[str, str]] = {
    "dark": {
        "connector": "#808080",
        "separator": "#585858",
        "input_border": "#444444",
        "banner": "#585858",
        "status_fg": "#727578",
    },
    "light": {
        "connector": "#808080",
        "separator": "#a0a0a0",
        "input_border": "#c0c0c0",
        "banner": "#a0a0a0",
        "status_fg": "#727578",
    },
}

NEUTRAL_PALETTE: dict[str, dict[str, str]] = {
    "dark": {"subtle": "#484848", "muted": "#707070", "normal": "#a0a0a0", "highlight": "#e0e0e0"},
    "light": {"subtle": "#b8b8b8", "muted": "#909090", "normal": "#606060", "highlight": "#202020"},
}

PEACEFUL_PALETTE: dict[str, dict[str, str]] = {
    "dark": {"subtle": "#303030", "muted": "#585858", "normal": "#bcbcbc", "highlight": "#eeeeee"},
    "light": {"subtle": "#e4e4e4", "muted": "#808080", "normal": "#444444", "highlight": "#080808"},
}


# --- Palette accessors ---

_KNOWN_AGENTS = frozenset(("claude", "gemini", "codex"))


def _safe_agent(agent: str) -> str:
    """Validate agent name. Unknown agents crash — they indicate a contract violation."""
    if agent not in _KNOWN_AGENTS:
        raise ValueError(f"Unknown agent '{agent}' — expected one of {sorted(_KNOWN_AGENTS)}")
    return agent


def _mode_key() -> str:
    return "dark" if _is_dark_mode else "light"


def get_agent_hex(agent: str, tier: str = "normal") -> str:
    """Hex color for an agent at a given tier."""
    return AGENT_PALETTE[_mode_key()][_safe_agent(agent)][tier]


def get_agent_normal_color(agent: str) -> str:
    """Hex color for agent's normal text color."""
    return get_agent_hex(agent, "normal")


def get_agent_highlight_color(agent: str) -> str:
    """Hex color for agent's highlight color (maximum contrast)."""
    return get_agent_hex(agent, "highlight")


def get_agent_muted_color(agent: str) -> str:
    """Hex color for agent's muted text color."""
    return get_agent_hex(agent, "muted")


def get_agent_subtle_color(agent: str) -> str:
    """Hex color for agent's subtle background tint."""
    return get_agent_hex(agent, "subtle")


def get_neutral_color(tier: str = "normal") -> str:
    """Hex color from neutral palette for the current mode."""
    return NEUTRAL_PALETTE[_mode_key()].get(tier, NEUTRAL_PALETTE[_mode_key()]["normal"])


def get_peaceful_color(tier: str = "normal") -> str:
    """Hex color from peaceful palette for the current mode."""
    return PEACEFUL_PALETTE[_mode_key()].get(tier, PEACEFUL_PALETTE[_mode_key()]["normal"])


def get_structural_color(key: str) -> str:
    """Hex color from structural palette for the current mode."""
    return STRUCTURAL_PALETTE[_mode_key()][key]


def get_connector_color() -> str:
    return get_structural_color("connector")


def get_banner_hex() -> str:
    return get_structural_color("banner")


def get_status_fg() -> str:
    return get_structural_color("status_fg")


# Backward-compat constant — connector is #808080 in both modes
CONNECTOR_COLOR = "#808080"


# --- Agent Hex Colors (for tmux pane backgrounds) ---

_LIGHT_MODE_PAPER_BG = "#fdf6e3"

_AGENT_PANE_INACTIVE_HAZE_PERCENTAGE_LIGHT = 0.12
_AGENT_PANE_INACTIVE_HAZE_PERCENTAGE_DARK = 0.18
_AGENT_PANE_TREE_SELECTED_HAZE_PERCENTAGE_LIGHT = 0.08
_AGENT_PANE_TREE_SELECTED_HAZE_PERCENTAGE_DARK = 0.12
_AGENT_PANE_ACTIVE_HAZE_PERCENTAGE = 0.0
_AGENT_STATUS_HAZE_PERCENTAGE = 0.06
_TUI_INACTIVE_HAZE_PERCENTAGE_LIGHT = 0.06
_TUI_INACTIVE_HAZE_PERCENTAGE_DARK = 0.12
_TERMINAL_HINT_WEIGHT = 0.35
_DARK_HINT_MAX_LUMINANCE = 0.45
_LIGHT_HINT_MIN_LUMINANCE = 0.55

_terminal_bg_cache: str | None = None


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
    return value if is_hex_color(value) else None


# Keep blend_colors as public alias for backward compat (used by banner.py)
blend_colors = blend


def get_terminal_background() -> str:
    """Get terminal's background color (hex), with mode-safe baseline and hint blending."""
    global _terminal_bg_cache  # noqa: PLW0603
    if _terminal_bg_cache:
        return _terminal_bg_cache
    mode_default_bg = "#000000" if _is_dark_mode else _LIGHT_MODE_PAPER_BG
    hint = _read_terminal_bg_from_appearance()
    if hint:
        lum = relative_luminance(hint)
        if _is_dark_mode and lum <= _DARK_HINT_MAX_LUMINANCE:
            _terminal_bg_cache = blend(mode_default_bg, hint, _TERMINAL_HINT_WEIGHT)
            return _terminal_bg_cache
        elif not _is_dark_mode and lum >= _LIGHT_HINT_MIN_LUMINANCE:
            _terminal_bg_cache = blend(mode_default_bg, hint, _TERMINAL_HINT_WEIGHT)
            return _terminal_bg_cache
    _terminal_bg_cache = mode_default_bg
    return _terminal_bg_cache


def get_tui_inactive_background() -> str:
    base_bg = get_terminal_background()
    blend_target = "#ffffff" if _is_dark_mode else "#000000"
    pct = _TUI_INACTIVE_HAZE_PERCENTAGE_DARK if _is_dark_mode else _TUI_INACTIVE_HAZE_PERCENTAGE_LIGHT
    return blend(base_bg, blend_target, pct)


def apply_tui_haze(hex_color: str) -> str:
    """Apply the TUI inactive haze to a color based on current mode."""
    blend_target = "#ffffff" if _is_dark_mode else "#000000"
    pct = _TUI_INACTIVE_HAZE_PERCENTAGE_DARK if _is_dark_mode else _TUI_INACTIVE_HAZE_PERCENTAGE_LIGHT
    return blend(hex_color, blend_target, pct)


def get_billboard_background(focused: bool) -> str:
    """Get billboard background color, ensuring it plays along with TUI focus state."""
    if _is_dark_mode:
        return "#242424" if focused else "#2b2b2b"
    return "#ffffff"


def _get_agent_pane_hex(agent: str) -> str:
    """Get the agent's muted hex color for pane background blending."""
    return get_agent_muted_color(agent)


def get_agent_pane_inactive_background(agent: str, haze_percentage: float | None = None) -> str:
    base_bg = get_terminal_background()
    agent_color = _get_agent_pane_hex(agent)
    pct = (
        (_AGENT_PANE_INACTIVE_HAZE_PERCENTAGE_DARK if _is_dark_mode else _AGENT_PANE_INACTIVE_HAZE_PERCENTAGE_LIGHT)
        if haze_percentage is None
        else haze_percentage
    )
    return blend(base_bg, agent_color, pct)


def get_agent_pane_selected_background(agent: str) -> str:
    return get_agent_pane_inactive_background(
        agent,
        haze_percentage=(
            _AGENT_PANE_TREE_SELECTED_HAZE_PERCENTAGE_DARK
            if _is_dark_mode
            else _AGENT_PANE_TREE_SELECTED_HAZE_PERCENTAGE_LIGHT
        ),
    )


def get_agent_pane_active_background(agent: str) -> str:
    return get_agent_pane_inactive_background(agent, haze_percentage=_AGENT_PANE_ACTIVE_HAZE_PERCENTAGE)


def get_agent_status_background(agent: str) -> str:
    base_bg = get_terminal_background()
    return blend(base_bg, _get_agent_pane_hex(agent), _AGENT_STATUS_HAZE_PERCENTAGE)


# --- Textual Themes ---


def _build_theme_variables(mode: str) -> dict[str, str]:
    """Build theme variables dict from palettes for a given mode."""
    agents = AGENT_PALETTE[mode]
    neutral = NEUTRAL_PALETTE[mode]
    structural = STRUCTURAL_PALETTE[mode]

    variables: dict[str, str] = {
        "block-cursor-text-style": "reverse",
        "scrollbar-background": get_terminal_background(),
    }

    # Agent colors
    for agent_name, tiers in agents.items():
        for tier, hex_val in tiers.items():
            variables[f"{agent_name}-{tier}"] = hex_val

    # Neutral gradient
    for tier, hex_val in neutral.items():
        variables[f"neutral-{tier}"] = hex_val

    # Structural
    variables["connector"] = structural["connector"]
    variables["separator"] = structural["separator"]
    variables["input-border"] = structural["input_border"]
    variables["banner-color"] = structural["banner"]
    variables["status-fg"] = structural["status_fg"]

    # Mode-specific UI chrome
    if mode == "dark":
        variables["input-selection-background"] = "#585858 50%"
        variables["scrollbar-color"] = "#444444"
        # Toast colors (blended from theme base colors)
        variables["warning-bg"] = "#3a3520"
        variables["warning-border"] = "#8a7530"
        variables["error-bg"] = "#3a2020"
        variables["error-border"] = "#8a3030"
    else:
        variables["input-selection-background"] = "#a0a0a0 50%"
        variables["scrollbar-color"] = "#c0c0c0"
        # Toast colors for light mode
        variables["warning-bg"] = "#f5ecd0"
        variables["warning-border"] = "#c8a840"
        variables["error-bg"] = "#f5d0d0"
        variables["error-border"] = "#c84040"

    return variables


_TELECLAUDE_DARK_THEME = Theme(
    name="teleclaude-dark",
    primary="#808080",
    secondary="#626262",
    accent="#585858",
    foreground="#d0d0d0",
    background=get_terminal_background(),
    success="#5faf5f",
    warning="#d7af5f",
    error="#d75f5f",
    surface="#262626",
    panel="#303030",
    dark=True,
    variables=_build_theme_variables("dark"),
)

_TELECLAUDE_LIGHT_THEME = Theme(
    name="teleclaude-light",
    primary="#808080",
    secondary="#9e9e9e",
    accent="#a8a8a8",
    foreground="#303030",
    background=get_terminal_background(),
    success="#3a8a3a",
    warning="#8a6a1a",
    error="#b03030",
    surface="#f0ead8",
    panel="#e8e0cc",
    dark=False,
    variables=_build_theme_variables("light"),
)

_TELECLAUDE_DARK_AGENT_THEME = Theme(
    name="teleclaude-dark-agent",
    primary="#808080",
    secondary="#626262",
    accent="#585858",
    foreground="#d0d0d0",
    background=get_terminal_background(),
    success="#5faf5f",
    warning="#d7af5f",
    error="#d75f5f",
    surface="#262626",
    panel="#303030",
    dark=True,
    variables=_TELECLAUDE_DARK_THEME.variables.copy(),
)

_TELECLAUDE_LIGHT_AGENT_THEME = Theme(
    name="teleclaude-light-agent",
    primary="#808080",
    secondary="#9e9e9e",
    accent="#a8a8a8",
    foreground="#303030",
    background=get_terminal_background(),
    success="#3a8a3a",
    warning="#8a6a1a",
    error="#b03030",
    surface="#f0ead8",
    panel="#e8e0cc",
    dark=False,
    variables=_TELECLAUDE_LIGHT_THEME.variables.copy(),
)


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


# --- Selection/preview hex colors ---


def get_agent_selection_bg_hex(agent: str) -> str:
    """Hex background for cursor-selected row (agent normal color)."""
    return get_agent_normal_color(agent)


def get_agent_preview_bg_hex(agent: str) -> str:
    """Hex background for preview row (agent muted color)."""
    return get_agent_muted_color(agent)


def get_selection_fg_hex() -> str:
    """Hex foreground for selected/preview rows (inverted text — terminal bg)."""
    return "#000000" if _is_dark_mode else "#ffffff"


# --- Rich Style Definitions for Textual Widgets ---

_agent_rich_colors: dict[str, dict[str, str]] = {}


def _build_rich_colors() -> None:
    """Rebuild Rich color tables for current dark/light mode from AGENT_PALETTE."""
    global _agent_rich_colors  # noqa: PLW0603
    _agent_rich_colors = AGENT_PALETTE[_mode_key()]


_build_rich_colors()


def get_agent_style(agent: str, tier: str = "normal") -> Style:
    """Get a Rich Style for an agent at a given tier."""
    safe = _safe_agent(agent)
    color = _agent_rich_colors[safe].get(tier, "default")
    bold = tier == "highlight"
    return Style(color=color, bold=bold)


def get_agent_color(agent: str, tier: str = "normal") -> str:
    """Get the hex color string for an agent at a given tier."""
    safe = _safe_agent(agent)
    return _agent_rich_colors[safe].get(tier, "default")


def get_agent_css_class(agent: str) -> str:
    """Get CSS class name for an agent."""
    return f"agent-{_safe_agent(agent)}"


# --- Theme-aware resolvers ---


def _peaceful_style(tier: str) -> Style:
    color = get_peaceful_color(tier)
    return Style(color=color, bold=tier == "highlight")


def _peaceful_color(tier: str) -> str:
    return get_peaceful_color(tier)


def resolve_style(agent: str | None, tier: str = "normal") -> Style:
    """Resolve a session style through the active theme.

    Agent theme (levels 1, 3, 4): agent-specific colors.
    Peaceful theme (levels 0, 2): neutral grays.
    None agent (shell session without active agent): always peaceful.
    """
    if agent and should_apply_session_theming():
        return get_agent_style(agent, tier)
    return _peaceful_style(tier)


def resolve_color(agent: str | None, tier: str = "normal") -> str:
    """Resolve a session color string through the active theme."""
    if agent and should_apply_session_theming():
        return get_agent_color(agent, tier)
    return _peaceful_color(tier)


def resolve_selection_bg_hex(agent: str | None) -> str:
    """Resolve selection background hex through the active theme."""
    if agent and should_apply_session_theming():
        return get_agent_selection_bg_hex(agent)
    return get_neutral_color("normal")


def resolve_preview_bg_hex(agent: str | None) -> str:
    """Resolve preview background hex through the active theme."""
    if agent and should_apply_session_theming():
        return get_agent_preview_bg_hex(agent)
    return get_neutral_color("muted")


# --- Agent status color (hex) ---


def get_agent_status_style(agent: str, *, muted: bool) -> Style:
    """Get Rich Style for agent status display (footer/modal)."""
    tier = "muted" if muted else "normal"
    return get_agent_style(agent, tier)


def get_agent_status_color(agent: str, *, muted: bool) -> str:
    """Return hex color for agent status display."""
    tier = "muted" if muted else "normal"
    return get_agent_hex(agent, tier)
