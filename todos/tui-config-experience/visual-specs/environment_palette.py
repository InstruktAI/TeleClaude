"""Environment 'Matrix Rain' section palette — xterm-256 color definitions.

Creative direction: The Matrix. Terminal green on black. The system's
internals made visible. Dark green base, brightening to neon highlight.
Red for danger/errors — a segfault in the Matrix.

Terminal requirement: TERM=xterm-256color for full palette.
Phase 2 registers these via curses.init_pair(pair_id, fg, bg=-1).
"""

from teleclaude.cli.tui.animation_colors import ColorPalette

# xterm-256 source of truth
ENVIRONMENT_COLORS = {
    "subtle": 22,  # dark green — deep background
    "muted": 28,  # forest green — resting state
    "normal": 34,  # green — active/readable
    "highlight": 46,  # bright green — neon emphasis
    "accent": 196,  # red — error/segfault
    "accent_2": 231,  # white — success flash
}

# Pair ID range: 83-88 (prototype allocation, Phase 2 formalizes)
ENVIRONMENT_PAIR_BASE = 83


class EnvironmentPalette(ColorPalette):
    """Environment section palette: 6 colors — green spectrum + red + white."""

    def __init__(self):
        super().__init__("environment")
        # Ordered: subtle(0), muted(1), normal(2), highlight(3), accent_red(4), accent_white(5)
        self.pair_ids = list(range(ENVIRONMENT_PAIR_BASE, ENVIRONMENT_PAIR_BASE + 6))

    def get(self, index: int) -> int:
        return self.pair_ids[index % len(self.pair_ids)]

    def __len__(self) -> int:
        return len(self.pair_ids)

    @staticmethod
    def init_colors():
        """Initialize curses color pairs. Call after curses.start_color()."""
        import curses

        colors = [
            ENVIRONMENT_COLORS["subtle"],
            ENVIRONMENT_COLORS["muted"],
            ENVIRONMENT_COLORS["normal"],
            ENVIRONMENT_COLORS["highlight"],
            ENVIRONMENT_COLORS["accent"],
            ENVIRONMENT_COLORS["accent_2"],
        ]
        for i, fg in enumerate(colors):
            curses.init_pair(ENVIRONMENT_PAIR_BASE + i, fg, -1)
