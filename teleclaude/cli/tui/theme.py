"""Agent colors and styling for TUI.

Color system with z-index layering:
- z=0: Base layer (main background)
- z=1: Tab view layer (content areas)
- z=2: Modal/popup layer (dialogs)

Prepares for future dark/light mode with system detection.
"""

import curses

# Agent color pair IDs (initialized after curses.start_color())
# Three colors per agent: muted (dim), normal (default), highlight (activity)
AGENT_COLORS: dict[str, dict[str, int]] = {
    "claude": {"muted": 1, "normal": 2, "highlight": 3},  # Orange tones
    "gemini": {"muted": 4, "normal": 5, "highlight": 6},  # Cyan tones
    "codex": {"muted": 7, "normal": 8, "highlight": 9},  # Green tones
}

# Z-index layer color pairs (for backgrounds)
# Dark mode: gradient from black (232) to lighter grays
# Light mode (future): gradient from white to darker grays
Z_LAYERS: dict[int, int] = {
    0: 11,  # Base: darkest (main background)
    1: 12,  # Tab views: slightly lighter
    2: 13,  # Modals: lightest
}

# Colors for selected items at each z-layer
Z_SELECTION: dict[int, int] = {
    0: 14,  # Base selection
    1: 15,  # Tab view selection
    2: 16,  # Modal selection
}


def init_colors() -> None:
    """Initialize curses color pairs for agents and layers.

    Three colors per agent:
    - muted: for inactive/idle content
    - normal: default display color (title line)
    - highlight: for active/changed content

    Z-layer colors for background gradients.
    """
    curses.start_color()
    curses.use_default_colors()

    # Claude (orange tones) - normal is the original Claude color
    curses.init_pair(1, 130, -1)  # Muted: dark orange/brown
    curses.init_pair(2, 172, -1)  # Normal: orange (original Claude color)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Highlight: bright yellow

    # Gemini (cyan tones)
    curses.init_pair(4, 24, -1)  # Muted: dark cyan
    curses.init_pair(5, 67, -1)  # Normal: cyan
    curses.init_pair(6, curses.COLOR_CYAN, -1)  # Highlight: bright cyan

    # Codex (green tones)
    curses.init_pair(7, 22, -1)  # Muted: dark green
    curses.init_pair(8, 65, -1)  # Normal: green
    curses.init_pair(9, curses.COLOR_GREEN, -1)  # Highlight: bright green

    # Disabled/unavailable
    curses.init_pair(10, curses.COLOR_WHITE, -1)

    # Z-layer background colors (dark mode gradient: black -> lighter)
    # Using 256-color palette: 232-255 are grayscale (232=black, 255=white)
    curses.init_pair(11, -1, 232)  # z=0: Base (near black)
    curses.init_pair(12, -1, 235)  # z=1: Tab views (dark gray)
    curses.init_pair(13, -1, 238)  # z=2: Modals (medium-dark gray)

    # Selection colors at each z-layer (brighter than layer bg)
    curses.init_pair(14, -1, 236)  # z=0 selection
    curses.init_pair(15, -1, 239)  # z=1 selection
    curses.init_pair(16, -1, 242)  # z=2 selection (modal selection)


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
