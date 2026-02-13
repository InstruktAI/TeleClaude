"""Agent colors and styling for TUI.

Color system with z-index layering:
- z=0: Base layer (main background)
- z=1: Tab view layer (content areas)
- z=2: Modal/popup layer (dialogs)

Detects macOS dark/light mode via system settings.
"""

import curses
import os
import re
import subprocess
import sys
from typing import Optional

from teleclaude.cli.tui.types import ThemeMode
from teleclaude.config import config

# Agent color pair IDs (initialized after curses.start_color())
# Three colors per agent: muted (dim), normal (default), highlight (activity)
AGENT_COLORS: dict[str, dict[str, int]] = {
    "claude": {"muted": 1, "normal": 2, "highlight": 3},  # Orange tones
    "gemini": {"muted": 4, "normal": 5, "highlight": 6},  # Cyan tones
    "codex": {"muted": 7, "normal": 8, "highlight": 9},  # Green tones
}

# Z-index layer color pairs (for backgrounds)
# Values set dynamically based on light/dark mode
Z_LAYERS: dict[int, int] = {
    0: 11,  # Base: darkest/lightest (main background)
    1: 12,  # Tab views: slightly offset
    2: 13,  # Modals: most offset from base
}

# Colors for selected items at each z-layer
Z_SELECTION: dict[int, int] = {
    0: 14,  # Base selection
    1: 15,  # Tab view selection
    2: 16,  # Modal selection
}

# Banner color pair
_BANNER_PAIR_ID = 22

# Tab line color pair (muted in dark mode)
_TAB_LINE_PAIR_ID = 23

# Track current mode for reference
_is_dark_mode: bool = True  # set at module load below, after is_dark_mode() is defined

# Status bar foreground color (neutral gray for both dark/light modes)
STATUS_FG_COLOR = "#727578"

# Agent highlight color codes (xterm 256) for active pane foreground
_AGENT_HIGHLIGHT_DARK = {
    "claude": 180,  # Light tan/beige
    "gemini": 183,  # Light purple
    "codex": 153,  # LightSlateGrey (light stone with blue)
}

_AGENT_HIGHLIGHT_LIGHT = {
    "claude": 94,  # Dark brown
    "gemini": 90,  # Soft lilac
    "codex": 24,  # Deep steel blue
}

_APPLE_DARK_LABEL = "Dark"


def _get_tmux_socket_path() -> Optional[str]:
    tmux_env = os.environ.get("TMUX")
    if not tmux_env:
        return None
    return tmux_env.split(",", 1)[0] or None


def _get_tmux_appearance_mode() -> Optional[str]:
    """Return tmux @appearance_mode if available (dark/light)."""
    tmux_bin = config.computer.tmux_binary
    socket_path = _get_tmux_socket_path()
    cmd = [tmux_bin]
    if socket_path:
        cmd.extend(["-S", socket_path])
    cmd.extend(["show", "-gv", "@appearance_mode"])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    mode = (result.stdout or "").strip().lower()
    if mode in {ThemeMode.DARK.value, ThemeMode.LIGHT.value}:
        return mode
    return None


def _get_env_appearance_mode() -> Optional[str]:
    """Return APPEARANCE_MODE if explicitly provided."""
    mode = (os.environ.get("APPEARANCE_MODE") or "").strip().lower()
    if mode in {ThemeMode.DARK.value, ThemeMode.LIGHT.value}:
        return mode
    return None


def _get_system_appearance_mode() -> Optional[str]:
    """Return host OS appearance mode when detectable."""
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
        return ThemeMode.DARK.value

    # macOS returns non-zero in light mode because the key is absent.
    # Only treat that exact case as light mode; any other failure is unknown.
    if result.returncode != 0:
        if "does not exist" in stderr or "could not be found" in stderr:
            return ThemeMode.LIGHT.value
        return None

    return ThemeMode.LIGHT.value


def get_system_dark_mode() -> bool | None:
    """Return host system dark mode when available, otherwise None."""
    mode = _get_system_appearance_mode()
    if mode is None:
        return None
    return mode == ThemeMode.DARK.value


def is_dark_mode() -> bool:
    """Resolve dark mode with stable precedence.

    Precedence:
    1) APPEARANCE_MODE env (explicit override)
    2) Host system mode (macOS)
    3) tmux @appearance_mode (fallback for non-macOS/session contexts)
    4) dark mode default

    Returns:
        True if dark mode, False if light mode
    """
    env_mode = _get_env_appearance_mode()
    if env_mode:
        return env_mode == ThemeMode.DARK.value

    system_mode = _get_system_appearance_mode()
    if system_mode:
        return system_mode == ThemeMode.DARK.value

    # On macOS, avoid tmux fallback when system mode probe is unavailable.
    # tmux @appearance_mode can flap when external watchers mis-detect mode.
    if sys.platform == "darwin":
        cached = globals().get("_is_dark_mode")
        if isinstance(cached, bool):
            return cached
        return True

    tmux_mode = _get_tmux_appearance_mode()
    if tmux_mode:
        return tmux_mode == ThemeMode.DARK.value

    # Default to dark mode if detection fails.
    return True


_is_dark_mode = is_dark_mode()


def get_current_mode() -> bool:
    """Get the current mode setting.

    Returns:
        True if dark mode, False if light mode
    """
    return _is_dark_mode


def init_colors() -> None:
    """Initialize curses color pairs for agents and layers.

    Three colors per agent:
    - muted: for inactive/idle content
    - normal: default display color (title line)
    - highlight: for active/changed content

    Z-layer colors adapt to light/dark mode:
    - Dark mode: 15% white (#262626) for inactive, terminal bg for active
    - Light mode: 85% white (#d9d9d9) for inactive, terminal bg for active
    """
    global _is_dark_mode, _terminal_bg_cache  # noqa: PLW0603
    curses.start_color()
    curses.use_default_colors()

    _is_dark_mode = is_dark_mode()
    # Reset terminal background hint cache on theme refresh so SIGUSR1 always
    # recomputes against current system mode/profile values.
    _terminal_bg_cache = None

    # Agent colors: invert muted/highlight between dark and light mode.
    # Dark mode: muted is darker, highlight is lighter.
    # Light mode: muted is lighter, highlight is darker.
    if _is_dark_mode:
        # Claude (terra/brown tones) - muted darker, highlight lighter in dark mode
        curses.init_pair(1, 94, -1)  # Muted: dark brown
        curses.init_pair(2, 137, -1)  # Normal: light brown/tan
        curses.init_pair(3, 180, -1)  # Highlight: light tan/beige

        # Gemini (lilac/purple tones) - muted darker, highlight lighter
        curses.init_pair(4, 103, -1)  # Muted: lighter purple for dark mode
        curses.init_pair(5, 141, -1)  # Normal: lilac
        curses.init_pair(6, 183, -1)  # Highlight: light purple

        # Codex (steel blue tones) - muted darker, highlight lighter
        curses.init_pair(7, 67, -1)  # Muted: deep steel blue
        curses.init_pair(8, 110, -1)  # Normal: CadetBlue (grey-blue balanced)
        curses.init_pair(9, 153, -1)  # Highlight: LightSlateGrey (light stone with blue)
    else:
        # Claude (terra/brown tones)
        curses.init_pair(1, 180, -1)  # Muted: light tan/beige
        curses.init_pair(2, 137, -1)  # Normal: light brown/tan
        curses.init_pair(3, 94, -1)  # Highlight: dark brown

        # Gemini (lilac/purple tones)
        curses.init_pair(4, 177, -1)  # Muted: light purple (slightly darker)
        curses.init_pair(5, 135, -1)  # Normal: lilac (slightly darker)
        curses.init_pair(6, 90, -1)  # Highlight: soft lilac (slightly darker)

        # Codex (steel blue tones)
        curses.init_pair(7, 110, -1)  # Muted: light steel blue (slightly darker)
        curses.init_pair(8, 67, -1)  # Normal: steel blue (bluish metal, less cyan)
        curses.init_pair(9, 24, -1)  # Highlight: deep steel blue (slightly darker)

    # Disabled/unavailable
    curses.init_pair(10, curses.COLOR_WHITE, -1)

    # Z-layer background colors
    # Use terminal default (-1) for all layers - let terminal theme shine through
    # Visual separation comes from borders, not background colors
    curses.init_pair(11, -1, -1)  # z=0: Base (terminal default)
    curses.init_pair(12, -1, -1)  # z=1: Tab views (terminal default)
    curses.init_pair(13, -1, -1)  # z=2: Modals (terminal default)

    # Selection colors - subtle highlight that works on any background
    if _is_dark_mode:
        curses.init_pair(14, -1, 238)  # z=0 selection
        curses.init_pair(15, -1, 239)  # z=1 selection
        curses.init_pair(16, -1, 240)  # z=2 selection (modal selection)

        # Modal shadow gradient (outer to inner: darker to lighter)
        # Creates depth effect around modal without changing modal bg
        curses.init_pair(17, 236, 234)  # Shadow layer 1 (outermost)
        curses.init_pair(18, 238, 235)  # Shadow layer 2
        curses.init_pair(19, 240, 236)  # Shadow layer 3 (closest to modal)

        # Modal border (crisp line on terminal default bg)
        curses.init_pair(20, 250, -1)  # Light gray border on default bg

        # Input field border
        curses.init_pair(21, 245, -1)  # Medium gray for input borders

        # Banner foreground (muted)
        curses.init_pair(_BANNER_PAIR_ID, 240, -1)

        # Tab lines (muted)
        curses.init_pair(_TAB_LINE_PAIR_ID, 240, -1)
    else:
        curses.init_pair(14, -1, 252)  # z=0 selection
        curses.init_pair(15, -1, 251)  # z=1 selection
        curses.init_pair(16, -1, 250)  # z=2 selection (modal selection)

        # Modal shadow gradient (outer to inner: lighter to darker)
        curses.init_pair(17, 250, 253)  # Shadow layer 1 (outermost)
        curses.init_pair(18, 247, 251)  # Shadow layer 2
        curses.init_pair(19, 244, 249)  # Shadow layer 3 (closest to modal)

        # Modal border (crisp line on terminal default bg)
        curses.init_pair(20, 236, -1)  # Dark gray border on default bg

        # Input field border
        curses.init_pair(21, 240, -1)  # Medium gray for input borders

        # Banner foreground (muted)
        curses.init_pair(_BANNER_PAIR_ID, 244, -1)

        # Tab lines (default for light mode)
        curses.init_pair(_TAB_LINE_PAIR_ID, 244, -1)


def get_layer_attr(z_index: int) -> int:
    """Get curses attribute for a z-layer background.

    Args:
        z_index: Layer depth (0=base, 1=tab views, 2=modals)

    Returns:
        Curses color pair attribute
    """
    pair_id = Z_LAYERS.get(z_index, Z_LAYERS[0])
    return curses.color_pair(pair_id)


def get_selection_attr(z_index: int) -> int:
    """Get curses attribute for selection at a z-layer.

    Args:
        z_index: Layer depth

    Returns:
        Curses color pair attribute
    """
    pair_id = Z_SELECTION.get(z_index, Z_SELECTION[0])
    return curses.color_pair(pair_id)


def get_modal_border_attr() -> int:
    """Get curses attribute for modal border (crisp line).

    Returns:
        Curses color pair attribute for modal border
    """
    return curses.color_pair(20)


def get_input_border_attr() -> int:
    """Get curses attribute for input field border.

    Returns:
        Curses color pair attribute for input border
    """
    return curses.color_pair(21)


def get_banner_attr(is_dark_mode: bool) -> int:
    """Get curses attribute for banner text.

    Args:
        is_dark_mode: True if dark mode, False if light mode

    Returns:
        Curses attribute for banner text
    """
    # if is_dark_mode:
    #     return curses.A_BOLD
    return curses.color_pair(_BANNER_PAIR_ID)


def get_tab_line_attr() -> int:
    """Get curses attribute for tab bar lines.

    Returns:
        Curses attribute for tab bar lines
    """
    if _is_dark_mode:
        return curses.color_pair(_TAB_LINE_PAIR_ID)
    return curses.A_NORMAL


# Agent color hex values (for tmux pane background hazes)
_AGENT_HEX_COLORS_DARK: dict[str, str] = {
    "claude": "#af875f",  # 137: light brown/tan
    "gemini": "#af87ff",  # 141: lilac/purple
    "codex": "#87afaf",  # 109: steel blue/cyan
}

_AGENT_HEX_COLORS_LIGHT: dict[str, str] = {
    "claude": "#af875f",  # 137: light brown/tan
    "gemini": "#af5fff",  # 135: darker lilac
    "codex": "#5f8787",  # 67: darker steel blue
}

# Soft paper baseline for light mode fallbacks (friendlier than pure white).
_LIGHT_MODE_PAPER_BG = "#fdf6e3"

# Configurable haze percentages (0.0 to 1.0)
# Restored tuned values used before recent regressions.
# Inactive session/preview pane background: 20% agent color, 80% base color
_HAZE_PERCENTAGE = 0.06
# Active pane background: no haze
_ACTIVE_HAZE_PERCENTAGE = 0.0

# Status bar background: 5% agent color, 95% base color (subtle)
_STATUS_HAZE_PERCENTAGE = 0.05
# TUI pane inactive haze kept softer than session/preview pane haze.
_TUI_INACTIVE_HAZE_PERCENTAGE = 0.06
# Terminal background hint weight: keep TUI palette stable while honoring terminal tone.
_TERMINAL_HINT_WEIGHT = 0.35
# Guardrails to reject hints that conflict with the current mode.
_DARK_HINT_MAX_LUMINANCE = 0.45
_LIGHT_HINT_MIN_LUMINANCE = 0.55

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_terminal_bg_cache: str | None = None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple.

    Args:
        hex_color: Hex color string (e.g., "#d78700")

    Returns:
        RGB tuple (r, g, b) with values 0-255
    """
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _is_hex_color(value: str) -> bool:
    """Return True when value is a #RRGGBB literal."""
    return bool(_HEX_COLOR_RE.match(value or ""))


def _relative_luminance(hex_color: str) -> float:
    """Return relative luminance (0.0=black, 1.0=white) for a #RRGGBB color."""
    r8, g8, b8 = _hex_to_rgb(hex_color)

    def _srgb_to_linear(v: int) -> float:
        c = v / 255.0
        if c <= 0.04045:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    r = _srgb_to_linear(r8)
    g = _srgb_to_linear(g8)
    b = _srgb_to_linear(b8)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _read_terminal_bg_from_appearance() -> str | None:
    """Best-effort terminal background probe via appearance helper."""
    appearance_bin = os.path.expanduser("~/.local/bin/appearance")
    if not os.path.exists(appearance_bin):
        return None
    try:
        result = subprocess.run(
            [appearance_bin, "get-terminal-bg"],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value if _is_hex_color(value) else None


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB tuple to hex color.

    Args:
        r: Red value (0-255)
        g: Green value (0-255)
        b: Blue value (0-255)

    Returns:
        Hex color string (e.g., "#d78700")
    """
    return f"#{r:02x}{g:02x}{b:02x}"


def blend_colors(base_hex: str, agent_hex: str, percentage: float) -> str:
    """Blend two colors with a configurable percentage.

    Formula: new_rgb = base_rgb × (1 - percentage) + agent_rgb × percentage

    Args:
        base_hex: Base color hex (e.g., "#202529")
        agent_hex: Agent color hex (e.g., "#d78700")
        percentage: Blend percentage (0.0 to 1.0, e.g., 0.10 for 10%)

    Returns:
        Blended hex color
    """
    base_r, base_g, base_b = _hex_to_rgb(base_hex)
    agent_r, agent_g, agent_b = _hex_to_rgb(agent_hex)

    blended_r = int(base_r * (1 - percentage) + agent_r * percentage)
    blended_g = int(base_g * (1 - percentage) + agent_g * percentage)
    blended_b = int(base_b * (1 - percentage) + agent_b * percentage)

    return _rgb_to_hex(blended_r, blended_g, blended_b)


def get_agent_pane_background(agent: str) -> str:
    """Get background color for an agent's pane with configurable haze.

    Blends the agent's color with the base inactive background color
    to create a subtle haze effect.

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        Hex color string for tmux window-style background
    """
    if _is_dark_mode:
        agent_colors = _AGENT_HEX_COLORS_DARK
    else:
        agent_colors = _AGENT_HEX_COLORS_LIGHT
    base_bg = get_terminal_background()

    agent_color = agent_colors.get(agent)
    if not agent_color:
        # Unknown agent: return base background
        return base_bg

    return blend_colors(base_bg, agent_color, _HAZE_PERCENTAGE * 3 if _is_dark_mode else _HAZE_PERCENTAGE)


def get_agent_active_pane_background(agent: str) -> str:
    """Get background color for an agent's active pane with very subtle haze.

    Blends the agent's color with the base inactive background color
    using the most subtle percentage for active panes.

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        Hex color string for tmux window-active-style background
    """
    if _is_dark_mode:
        agent_colors = _AGENT_HEX_COLORS_DARK
    else:
        agent_colors = _AGENT_HEX_COLORS_LIGHT
    base_bg = get_terminal_background()

    agent_color = agent_colors.get(agent)
    if not agent_color:
        # Unknown agent: return base background
        return base_bg

    return blend_colors(base_bg, agent_color, _ACTIVE_HAZE_PERCENTAGE * 3 if _is_dark_mode else _ACTIVE_HAZE_PERCENTAGE)


def get_agent_status_background(agent: str) -> str:
    """Get background color for an agent's status bar with subtle haze.

    Blends the agent's color with the base inactive background color
    using a more subtle percentage for status bars.

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        Hex color string for tmux status-style background
    """
    if _is_dark_mode:
        agent_colors = _AGENT_HEX_COLORS_DARK
    else:
        agent_colors = _AGENT_HEX_COLORS_LIGHT
    base_bg = get_terminal_background()

    agent_color = agent_colors.get(agent)
    if not agent_color:
        # Unknown agent: return base background
        return base_bg

    return blend_colors(base_bg, agent_color, _STATUS_HAZE_PERCENTAGE * 3 if _is_dark_mode else _STATUS_HAZE_PERCENTAGE)


def get_agent_highlight_color(agent: str) -> int:
    """Get xterm 256 color code for agent's highlight color (for active pane foreground).

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        xterm 256 color code for the agent's highlight color (default: 153)
    """
    if _is_dark_mode:
        return _AGENT_HIGHLIGHT_DARK.get(agent, 153)
    return _AGENT_HIGHLIGHT_LIGHT.get(agent, 24)


def get_terminal_background() -> str:
    """Get the terminal's actual default background color.

    Uses a mode-safe baseline and optionally blends with a terminal hint.

    Returns:
        Hex color string for terminal background
    """
    global _terminal_bg_cache  # noqa: PLW0603

    if _terminal_bg_cache:
        return _terminal_bg_cache

    mode_default_bg = "#000000" if _is_dark_mode else _LIGHT_MODE_PAPER_BG
    hint = _read_terminal_bg_from_appearance()
    if hint:
        hint_luminance = _relative_luminance(hint)
        if _is_dark_mode:
            if hint_luminance <= _DARK_HINT_MAX_LUMINANCE:
                _terminal_bg_cache = blend_colors(mode_default_bg, hint, _TERMINAL_HINT_WEIGHT)
                return _terminal_bg_cache
        elif hint_luminance >= _LIGHT_HINT_MIN_LUMINANCE:
            _terminal_bg_cache = blend_colors(mode_default_bg, hint, _TERMINAL_HINT_WEIGHT)
            return _terminal_bg_cache

    _terminal_bg_cache = mode_default_bg
    return _terminal_bg_cache


def get_tui_inactive_background() -> str:
    """Get subtle inactive haze for the TUI pane from terminal background."""
    base_bg = get_terminal_background()
    blend_target = "#ffffff" if _is_dark_mode else "#000000"
    return blend_colors(
        base_bg, blend_target, _TUI_INACTIVE_HAZE_PERCENTAGE * 3 if _is_dark_mode else _TUI_INACTIVE_HAZE_PERCENTAGE
    )


def get_agent_muted_color(agent: str) -> int:
    """Get xterm 256 color code for agent's muted color (for active pane foreground).

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        xterm 256 color code for the agent's muted color
    """
    # In dark mode: claude=94, gemini=103, codex=67
    # In light mode: claude=180, gemini=177, codex=110
    if _is_dark_mode:
        return {"claude": 94, "gemini": 103, "codex": 67}.get(agent, 94)
    return {"claude": 180, "gemini": 177, "codex": 110}.get(agent, 180)


def get_agent_normal_color(agent: str) -> int:
    """Get xterm 256 color code for agent's normal color (for inactive pane foreground).

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        xterm 256 color code for the agent's normal color
    """
    # Map agent to their color pair ID (normal = second color)
    agent_pairs = {
        "claude": 2,
        "gemini": 5,
        "codex": 8,
    }
    pair_id = agent_pairs.get(agent, 2)

    # Extract the color code from the pair
    # In dark mode: claude=137, gemini=141, codex=110
    # In light mode: claude=137, gemini=135, codex=67
    if _is_dark_mode:
        return {2: 137, 5: 141, 8: 110}.get(pair_id, 137)
    return {2: 137, 5: 135, 8: 67}.get(pair_id, 137)
