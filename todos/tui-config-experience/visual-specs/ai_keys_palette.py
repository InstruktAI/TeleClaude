"""AI Keys 'Key Shimmer' section palette — xterm-256 color definitions.

Creative direction: Gold and treasure. The feeling of unlocking something
valuable. Dark goldenrod base, building to bright gold highlights with
white sparkle. Dark red for error/danger — the vault didn't open.

Terminal requirement: TERM=xterm-256color for full palette.
Phase 2 registers these via curses.init_pair(pair_id, fg, bg=-1).
"""

from teleclaude.cli.tui.animation_colors import ColorPalette

# xterm-256 source of truth
AI_KEYS_COLORS = {
    "subtle": 94,  # dark goldenrod — deep background
    "muted": 136,  # dark khaki — resting state
    "normal": 178,  # gold — active/readable
    "highlight": 220,  # bright gold — emphasis
    "accent_1": 231,  # white — flash/sparkle peak
    "accent_2": 88,  # dark red — error/danger
}

# Pair ID range: 55-60 (prototype allocation, Phase 2 formalizes)
AI_KEYS_PAIR_BASE = 55


class AIKeysPalette(ColorPalette):
    """AI Keys section palette: 6 colors from dark gold to white + red error."""

    def __init__(self):
        super().__init__("ai_keys")
        # Ordered: subtle(0), muted(1), normal(2), highlight(3), accent_white(4), accent_red(5)
        self.pair_ids = list(range(AI_KEYS_PAIR_BASE, AI_KEYS_PAIR_BASE + 6))

    def get(self, index: int) -> int:
        return self.pair_ids[index % len(self.pair_ids)]

    def __len__(self) -> int:
        return len(self.pair_ids)

    @staticmethod
    def init_colors():
        """Initialize curses color pairs. Call after curses.start_color()."""
        import curses

        colors = [
            AI_KEYS_COLORS["subtle"],
            AI_KEYS_COLORS["muted"],
            AI_KEYS_COLORS["normal"],
            AI_KEYS_COLORS["highlight"],
            AI_KEYS_COLORS["accent_1"],
            AI_KEYS_COLORS["accent_2"],
        ]
        for i, fg in enumerate(colors):
            curses.init_pair(AI_KEYS_PAIR_BASE + i, fg, -1)
