"""Agent colors and styling for TUI."""

import curses

# Agent color pair IDs (initialized after curses.start_color())
AGENT_COLORS: dict[str, dict[str, int]] = {
    "claude": {"bright": 1, "muted": 2},  # Orange tones
    "gemini": {"bright": 3, "muted": 4},  # Cyan tones
    "codex": {"bright": 5, "muted": 6},  # Green tones
}


def init_colors() -> None:
    """Initialize curses color pairs for agents."""
    curses.start_color()
    curses.use_default_colors()

    # Claude (bright/muted orange/yellow)
    curses.init_pair(1, curses.COLOR_YELLOW, -1)
    curses.init_pair(2, 172, -1)  # Muted yellow/orange

    # Gemini (bright/muted cyan)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, 67, -1)  # Muted cyan

    # Codex (bright/muted green)
    curses.init_pair(5, curses.COLOR_GREEN, -1)
    curses.init_pair(6, 65, -1)  # Muted green

    # Disabled/unavailable
    curses.init_pair(7, curses.COLOR_WHITE, -1)
