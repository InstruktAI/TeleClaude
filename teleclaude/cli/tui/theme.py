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
# Four colors per agent: subtle (tint), muted (dim), normal (default), highlight (activity)
AGENT_COLORS: dict[str, dict[str, int]] = {
    "claude": {"subtle": 1, "muted": 2, "normal": 3, "highlight": 41},  # Orange tones
    "gemini": {"subtle": 4, "muted": 5, "normal": 6, "highlight": 42},  # Cyan tones
    "codex": {"subtle": 7, "muted": 8, "normal": 9, "highlight": 43},  # Green tones
}

AGENT_PREVIEW_SELECTED_BG_PAIRS: dict[str, int] = {
    "claude": 27,
    "gemini": 28,
    "codex": 29,
}

AGENT_PREVIEW_SELECTED_FOCUS_PAIRS: dict[str, int] = {
    "claude": 37,
    "gemini": 38,
    "codex": 39,
}

AGENT_PREVIEW_SELECTED_BG_PAIRS_SEMI: dict[str, int] = {
    "claude": 52,
    "gemini": 53,
    "codex": 54,
}

AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_SEMI: dict[str, int] = {
    "claude": 55,
    "gemini": 56,
    "codex": 57,
}

AGENT_PREVIEW_SELECTED_BG_PAIRS_HIGHLIGHT: dict[str, int] = {
    "claude": 64,
    "gemini": 65,
    "codex": 66,
}

AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_HIGHLIGHT: dict[str, int] = {
    "claude": 67,
    "gemini": 68,
    "codex": 69,
}

AGENT_PREVIEW_SELECTED_BG_PAIRS_OFF: dict[str, int] = {
    "claude": 58,
    "gemini": 59,
    "codex": 60,
}

AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_OFF: dict[str, int] = {
    "claude": 61,
    "gemini": 62,
    "codex": 63,
}

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
    PANE_THEMING_MODE_SEMI: 3,
    PANE_THEMING_MODE_FULL: 4,
}
_PANE_LEVEL_TO_CANONICAL_MODE: tuple[str, str, str, str, str] = (
    PANE_THEMING_MODE_OFF,
    PANE_THEMING_MODE_HIGHLIGHT,
    PANE_THEMING_MODE_HIGHLIGHT_EXT,
    PANE_THEMING_MODE_AGENT,
    PANE_THEMING_MODE_AGENT_PLUS,
)
_VALID_PANE_THEMING_MODES = set(_PANE_THEMING_MODE_TO_LEVEL)

# Optional process-scoped override for runtime UI toggles.
_PANE_THEMING_MODE_OVERRIDE: str | None = None

STICKY_BADGE_PAIR_ID = 40

DEFAULT_FOREGROUND_COLOR_DARK_MODE = curses.COLOR_BLACK
DEFAULT_BACKGROUND_COLOR_DARK_MODE = curses.COLOR_WHITE
DEFAULT_FOREGROUND_COLOR_LIGHT_MODE = curses.COLOR_BLACK
DEFAULT_BACKGROUND_COLOR_LIGHT_MODE = curses.COLOR_WHITE

STICKY_BADGE_FG = -1  # terminal default — inverted via A_REVERSE
STICKY_BADGE_BG = -1  # terminal default — inverted via A_REVERSE

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

# Peaceful mode grayscale pairs (level 0: no agent color, just calm grays)
_PEACEFUL_NORMAL_PAIR_ID = 50
_PEACEFUL_MUTED_PAIR_ID = 51

# Track current mode for reference
_is_dark_mode: bool = True  # set at module load below, after is_dark_mode() is defined

# Status bar foreground color (neutral gray for both dark/light modes)
STATUS_FG_COLOR = "#727578"

# Agent xterm 256 color codes per tier (for tmux pane foreground and external references)
_AGENT_SUBTLE_DARK = {"claude": 94, "gemini": 103, "codex": 67}
_AGENT_SUBTLE_LIGHT = {"claude": 180, "gemini": 177, "codex": 110}

_AGENT_MUTED_DARK = {"claude": 137, "gemini": 141, "codex": 110}
_AGENT_MUTED_LIGHT = {"claude": 137, "gemini": 135, "codex": 67}

_AGENT_NORMAL_DARK = {"claude": 180, "gemini": 183, "codex": 153}
_AGENT_NORMAL_LIGHT = {"claude": 94, "gemini": 90, "codex": 24}

# Highlight: maximum contrast for activity bursts
_AGENT_HIGHLIGHT_DARK = {"claude": 231, "gemini": 231, "codex": 231}
_AGENT_HIGHLIGHT_LIGHT = {"claude": 16, "gemini": 16, "codex": 16}

_APPLE_DARK_LABEL = "Dark"
_DEFAULT_AGENT = "codex"


def _safe_agent(agent: str) -> str:
    """Normalize unknown agent names to a stable default."""
    return agent if agent in AGENT_COLORS else _DEFAULT_AGENT


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

    Four colors per agent:
    - subtle: lightest tint (highlighted row backgrounds, headless sessions)
    - muted: subdued text (unavailable agents, dim content)
    - normal: default rendering color (session titles, pane foreground)
    - highlight: maximum contrast activity bursts (white in dark, black in light)

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

    # Agent colors: invert subtle/normal between dark and light mode.
    # Dark mode: subtle is darker, normal is lighter.
    # Light mode: subtle is lighter, normal is darker.
    if _is_dark_mode:
        # Claude (terra/brown tones)
        curses.init_pair(1, 94, -1)  # Subtle: dark brown (tint/background)
        curses.init_pair(2, 137, -1)  # Muted: light brown/tan (subdued text)
        curses.init_pair(3, 180, -1)  # Normal: light tan/beige (default text)

        # Gemini (lilac/purple tones)
        curses.init_pair(4, 103, -1)  # Subtle: lighter purple (tint/background)
        curses.init_pair(5, 141, -1)  # Muted: lilac (subdued text)
        curses.init_pair(6, 183, -1)  # Normal: light purple (default text)

        # Codex (steel blue tones)
        curses.init_pair(7, 67, -1)  # Subtle: deep steel blue (tint/background)
        curses.init_pair(8, 110, -1)  # Muted: CadetBlue (subdued text)
        curses.init_pair(9, 153, -1)  # Normal: LightSlateGrey (default text)

        # Highlight: pure white for activity bursts (maximum contrast)
        curses.init_pair(41, 231, -1)  # Claude highlight
        curses.init_pair(42, 231, -1)  # Gemini highlight
        curses.init_pair(43, 231, -1)  # Codex highlight

    else:
        # Claude (terra/brown tones)
        curses.init_pair(1, 180, -1)  # Subtle: light tan/beige (tint/background)
        curses.init_pair(2, 137, -1)  # Muted: light brown/tan (subdued text)
        curses.init_pair(3, 94, -1)  # Normal: dark brown (default text)

        # Gemini (lilac/purple tones)
        curses.init_pair(4, 177, -1)  # Subtle: light purple (tint/background)
        curses.init_pair(5, 135, -1)  # Muted: lilac (subdued text)
        curses.init_pair(6, 90, -1)  # Normal: soft lilac (default text)

        # Codex (steel blue tones)
        curses.init_pair(7, 110, -1)  # Subtle: light steel blue (tint/background)
        curses.init_pair(8, 67, -1)  # Muted: steel blue (subdued text)
        curses.init_pair(9, 24, -1)  # Normal: deep steel blue (default text)

        # Highlight: pure black for activity bursts (maximum contrast)
        curses.init_pair(41, 16, -1)  # Claude highlight
        curses.init_pair(42, 16, -1)  # Gemini highlight
        curses.init_pair(43, 16, -1)  # Codex highlight

    # Peaceful mode grays (level 0): neutral grayscale, no agent tint.
    if _is_dark_mode:
        curses.init_pair(_PEACEFUL_NORMAL_PAIR_ID, 250, -1)  # 70% gray
        curses.init_pair(_PEACEFUL_MUTED_PAIR_ID, 240, -1)  # 40% gray
    else:
        curses.init_pair(_PEACEFUL_NORMAL_PAIR_ID, 238, -1)  # 30% gray
        curses.init_pair(_PEACEFUL_MUTED_PAIR_ID, 244, -1)  # 60% gray

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

        # Preparation view status colors
        curses.init_pair(25, 71, -1)  # Green (ready)
        curses.init_pair(26, 178, -1)  # Yellow (active)
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

        # Preparation view status colors
        curses.init_pair(25, 28, -1)  # Green (ready)
        curses.init_pair(26, 136, -1)  # Yellow (active)

    # Terminal background as text color gives inverted badge rows.
    _term_bg_fg = 16 if _is_dark_mode else 231

    for agent in AGENT_COLORS:
        # Full mode: terminal-bg text on agent muted/normal background.
        curses.init_pair(
            AGENT_PREVIEW_SELECTED_BG_PAIRS[agent],
            _term_bg_fg,
            get_agent_muted_color(agent),
        )
        curses.init_pair(
            AGENT_PREVIEW_SELECTED_FOCUS_PAIRS[agent],
            _term_bg_fg,
            get_agent_normal_color(agent),
        )

        # Semi mode: same inversion on agent muted/normal background.
        curses.init_pair(
            AGENT_PREVIEW_SELECTED_BG_PAIRS_SEMI[agent],
            _term_bg_fg,
            get_agent_muted_color(agent),
        )
        curses.init_pair(
            AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_SEMI[agent],
            _term_bg_fg,
            get_agent_normal_color(agent),
        )

        # Off mode: neutral gray highlights with terminal-bg text for crisp inversion.
        # 50% gray bg for preview, 70% gray bg for focus — same in both color schemes.
        curses.init_pair(AGENT_PREVIEW_SELECTED_BG_PAIRS_OFF[agent], _term_bg_fg, 244)  # 50% gray
        curses.init_pair(AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_OFF[agent], _term_bg_fg, 250)  # 70% gray

        # Highlight mode: same inversion on agent muted/normal background.
        curses.init_pair(
            AGENT_PREVIEW_SELECTED_BG_PAIRS_HIGHLIGHT[agent],
            _term_bg_fg,
            get_agent_muted_color(agent),
        )
        curses.init_pair(
            AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_HIGHLIGHT[agent],
            _term_bg_fg,
            get_agent_normal_color(agent),
        )

    # Disabled/unavailable
    curses.init_pair(10, curses.COLOR_WHITE, -1)

    # Sticky badge uses terminal defaults with A_REVERSE for inversion.
    curses.init_pair(STICKY_BADGE_PAIR_ID, STICKY_BADGE_FG, STICKY_BADGE_BG)


def get_sticky_badge_attr() -> int:
    """Get curses attribute for sticky badge indicator.

    This is a standalone badge style contract:
    - Uses terminal defaults (-1, -1) with A_REVERSE for inversion, matching
      the terminal's native typography instead of hard COLOR_BLACK/COLOR_WHITE.
    - The caller may add only bold for row selection.
    - Never alter this function to satisfy row/preview highlighting requirements.
    """
    return curses.color_pair(STICKY_BADGE_PAIR_ID) | curses.A_REVERSE


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

# Configurable haze percentages (0.0 to 1.0) per UI state.
# Agent preview pane states:
# Inactive panes should stay clearly distinct from active ones.
_AGENT_PANE_INACTIVE_HAZE_PERCENTAGE = 0.18
# Tree-selected pane gets a lighter visual cue while remaining distinct.
_AGENT_PANE_TREE_SELECTED_HAZE_PERCENTAGE = 0.08
_AGENT_PANE_ACTIVE_HAZE_PERCENTAGE = 0.0

# Status-like background accents:
_AGENT_STATUS_HAZE_PERCENTAGE = 0.06

# TUI pane inactive haze, split out for mode-specific tuning.
_TUI_INACTIVE_HAZE_PERCENTAGE_LIGHT = 0.06
_TUI_INACTIVE_HAZE_PERCENTAGE_DARK = 0.12
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


def get_agent_pane_inactive_background(agent: str, haze_percentage: float | None = None) -> str:
    """Get background color for an agent's inactive pane with configurable haze.

    Blends the agent's color with the base inactive background color
    to create a subtle haze effect.

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    haze_percentage: Blend percentage (0.0–1.0); defaults to inactive haze.

    Returns:
        Hex color string for tmux window-style background.
    """
    if _is_dark_mode:
        agent_colors = _AGENT_HEX_COLORS_DARK
    else:
        agent_colors = _AGENT_HEX_COLORS_LIGHT
    base_bg = get_terminal_background()

    agent_color = agent_colors[_safe_agent(agent)]
    percentage = _AGENT_PANE_INACTIVE_HAZE_PERCENTAGE if haze_percentage is None else haze_percentage
    return blend_colors(base_bg, agent_color, percentage)


def get_agent_pane_selected_background(agent: str) -> str:
    """Get background color for a selected tree row without focus.

    Uses a lighter haze to preserve strong contrast with neighboring inactive
    panes while staying in the muted preview palette.
    """
    return get_agent_pane_inactive_background(agent, haze_percentage=_AGENT_PANE_TREE_SELECTED_HAZE_PERCENTAGE)


def get_agent_pane_active_background(agent: str) -> str:
    """Get background color for an active pane (no haze).

    Uses a 0% haze blend for terminal-accurate active styling so foreground
    remains independent from inactive/selected preview treatment.
    """
    return get_agent_pane_inactive_background(agent, haze_percentage=_AGENT_PANE_ACTIVE_HAZE_PERCENTAGE)


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

    agent_color = agent_colors[_safe_agent(agent)]
    return blend_colors(base_bg, agent_color, _AGENT_STATUS_HAZE_PERCENTAGE)


def get_agent_normal_color(agent: str) -> int:
    """Get xterm 256 color code for agent's normal color (default text, pane foreground).

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        xterm 256 color code for the agent's normal color
    """
    key = _safe_agent(agent)
    if _is_dark_mode:
        return _AGENT_NORMAL_DARK[key]
    return _AGENT_NORMAL_LIGHT[key]


def get_agent_highlight_color(agent: str) -> int:
    """Get xterm 256 color code for agent's highlight color (activity bursts, maximum contrast).

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        xterm 256 color code (231=bright white in dark, 16=true black in light)
    """
    key = _safe_agent(agent)
    if _is_dark_mode:
        return _AGENT_HIGHLIGHT_DARK[key]
    return _AGENT_HIGHLIGHT_LIGHT[key]


def get_agent_status_color_pair(agent: str, *, muted: bool) -> int:
    """Get the agent pair for status-style UI elements (footer/modal).

    Uses the normal foreground for active/available states and muted foreground for
    unavailable states so footer and modal chips stay on the normal text intent.
    """
    safe_agent = _safe_agent(agent)
    key = "muted" if muted else "normal"
    return AGENT_COLORS[safe_agent][key]


def get_agent_subtle_attr(agent: str) -> int:
    """Get curses attribute for subtle agent tint (default row tint)."""
    return curses.color_pair(AGENT_COLORS[_safe_agent(agent)]["subtle"])


def get_agent_normal_attr(agent: str) -> int:
    """Get curses attribute for normal agent row text."""
    return curses.color_pair(AGENT_COLORS[_safe_agent(agent)]["normal"])


def get_agent_highlight_attr(agent: str) -> int:
    """Get curses attribute for highlighted agent emphasis."""
    return curses.color_pair(AGENT_COLORS[_safe_agent(agent)]["highlight"])


def get_peaceful_normal_attr() -> int:
    """Curses attr for peaceful mode normal text (80% gray)."""
    return curses.color_pair(_PEACEFUL_NORMAL_PAIR_ID)


def get_peaceful_muted_attr() -> int:
    """Curses attr for peaceful mode muted text (60% gray, headless sessions)."""
    return curses.color_pair(_PEACEFUL_MUTED_PAIR_ID)


def get_pane_theming_mode() -> str:
    """Return effective pane theming mode from config.

    Supported:
      - "highlight": minimal mode: highlight text on native foreground intent
      - "highlight2": same as highlight with two fill indicators
      - "agent": theme agent-tinted text with foreground overrides
      - "agent_plus": stronger agent mode with higher contrast accents
      - legacy aliases: "full" -> "agent_plus", "semi" -> "agent"
      - "off": no forced foreground in preview rows and pane foregrounds
    """
    if _PANE_THEMING_MODE_OVERRIDE:
        return _PANE_THEMING_MODE_OVERRIDE

    configured_mode = str(config.ui.pane_theming_mode)  # type: ignore[attr-defined]
    try:
        return normalize_pane_theming_mode(configured_mode)
    except ValueError:
        return PANE_THEMING_MODE_AGENT_PLUS


def get_pane_theming_mode_level(mode: str | None = None) -> int:
    """Return 0..4 numeric level for the current or supplied pane theming mode."""
    canonical_mode = normalize_pane_theming_mode(mode if mode is not None else get_pane_theming_mode())
    return _PANE_THEMING_MODE_TO_LEVEL[canonical_mode]


def get_pane_theming_row_style_level(mode: str | None = None) -> int:
    """Return row-style level used by tree/panel renderers.

    The tree style intentionally uses fewer semantic states than the raw cycle:
    0 -> peaceful/off
    1 -> highlight-only
    2 -> extended highlight
    3 -> semi/partial
    4 -> full
    """
    mode_level = get_pane_theming_mode_level(mode)
    return mode_level


def should_apply_session_theming(level: int | None = None) -> bool:
    """Whether session pane foreground should use agent colors instead of terminal default."""
    pane_level = get_pane_theming_mode_level() if level is None else level
    return pane_level in (1, 3, 4)


def should_apply_paint_pane_theming(level: int | None = None) -> bool:
    """Whether paint payload panes should apply agent-themed foreground text."""
    pane_level = get_pane_theming_mode_level() if level is None else level
    return pane_level == 3


def normalize_pane_theming_mode(mode: str) -> str:
    """Normalize pane theming mode to one canonical state."""
    canonical_mode = (mode or "").strip().lower()
    canonical_mode = _PANE_THEMING_MODE_CANONICAL.get(canonical_mode, canonical_mode)
    if canonical_mode not in _VALID_PANE_THEMING_MODES:
        raise ValueError(f"Invalid pane_theming_mode: {mode}")
    return canonical_mode


def get_pane_theming_mode_from_level(level: int) -> str:
    """Convert mode level to canonical mode string."""
    if level < 0 or level >= len(_PANE_LEVEL_TO_CANONICAL_MODE):
        raise ValueError(f"pane_theming_mode level must be 0..{len(_PANE_LEVEL_TO_CANONICAL_MODE) - 1}")
    return _PANE_LEVEL_TO_CANONICAL_MODE[level]


def get_pane_theming_mode_cycle() -> tuple[str, ...]:
    """Expose canonical cycle order for UI toggles."""
    return PANE_THEMING_MODE_CYCLE


def set_pane_theming_mode(mode: str | None) -> None:
    """Set runtime override for pane theming mode.

    Args:
        mode: "off" | "highlight" | "highlight2" | "agent" | "agent_plus" or legacy
            aliases "full"/"semi"/None to clear override.
    """
    global _PANE_THEMING_MODE_OVERRIDE  # noqa: PLW0603
    if not mode:
        _PANE_THEMING_MODE_OVERRIDE = None  # type: ignore[reportConstantRedefinition]
        return
    _PANE_THEMING_MODE_OVERRIDE = normalize_pane_theming_mode(mode)  # type: ignore[reportConstantRedefinition]


def get_agent_preview_selected_bg_attr(agent: str) -> int:
    """Get curses attribute for a preview-selected (non-focused) row.

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        Curses attribute for agent-specific preview selection style.
    """
    safe_agent = _safe_agent(agent)
    style_level = get_pane_theming_row_style_level()
    if style_level in (0, 2):
        return curses.color_pair(AGENT_PREVIEW_SELECTED_BG_PAIRS_OFF[safe_agent]) | curses.A_BOLD
    if style_level == 1:
        pair_id = AGENT_PREVIEW_SELECTED_BG_PAIRS_HIGHLIGHT[safe_agent]
    elif style_level == 3:
        pair_id = AGENT_PREVIEW_SELECTED_BG_PAIRS_SEMI[safe_agent]
    else:
        pair_id = AGENT_PREVIEW_SELECTED_BG_PAIRS[safe_agent]
    return curses.color_pair(pair_id) | curses.A_BOLD


def get_agent_preview_selected_focus_attr(agent: str) -> int:
    """Get curses attribute for a focused preview row.

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        Curses attribute for agent-specific focused preview row.
    """
    safe_agent = _safe_agent(agent)
    style_level = get_pane_theming_row_style_level()
    if style_level in (0, 2):
        return curses.color_pair(AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_OFF[safe_agent]) | curses.A_BOLD
    if style_level == 1:
        pair_id = AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_HIGHLIGHT[safe_agent]
    elif style_level == 3:
        pair_id = AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_SEMI[safe_agent]
    else:
        pair_id = AGENT_PREVIEW_SELECTED_FOCUS_PAIRS[safe_agent]
    return curses.color_pair(pair_id) | curses.A_BOLD


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
        base_bg,
        blend_target,
        _TUI_INACTIVE_HAZE_PERCENTAGE_DARK if _is_dark_mode else _TUI_INACTIVE_HAZE_PERCENTAGE_LIGHT,
    )


def get_agent_subtle_color(agent: str) -> int:
    """Get xterm 256 color code for agent's subtle color (lightest tint for backgrounds).

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        xterm 256 color code for the agent's subtle color
    """
    key = _safe_agent(agent)
    if _is_dark_mode:
        return _AGENT_SUBTLE_DARK[key]
    return _AGENT_SUBTLE_LIGHT[key]


def get_agent_muted_color(agent: str) -> int:
    """Get xterm 256 color code for agent's muted color (subdued text).

    Args:
        agent: Agent name ("claude", "gemini", "codex", or unknown)

    Returns:
        xterm 256 color code for the agent's muted color
    """
    key = _safe_agent(agent)
    if _is_dark_mode:
        return _AGENT_MUTED_DARK[key]
    return _AGENT_MUTED_LIGHT[key]
