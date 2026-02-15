"""Telegram 'Blue Sky' section palette — xterm-256 color definitions.

Creative direction: Telegram's sky-blue identity. Cool, clean, trustworthy.
The palette moves from deep ocean (subtle) through sky (normal) to bright
cloud-white (accent). Feels like looking up on a clear day.

Terminal requirement: TERM=xterm-256color for full palette.
Phase 2 registers these via curses.init_pair(pair_id, fg, bg=-1).
"""

from teleclaude.cli.tui.animation_colors import ColorPalette

# xterm-256 source of truth
TELEGRAM_COLORS = {
    "subtle": 24,  # deep blue — resting/background state
    "muted": 31,  # cerulean — default idle tone
    "normal": 38,  # deep sky blue — active/readable
    "highlight": 117,  # light sky blue — emphasis, attention
    "accent": 231,  # white — flash/celebration peak
}

# Pair ID range: 50-54 (prototype allocation, Phase 2 formalizes)
TELEGRAM_PAIR_BASE = 50


class TelegramPalette(ColorPalette):
    """Telegram section palette: 5 colors from deep blue to white."""

    def __init__(self):
        super().__init__("telegram")
        # Ordered: subtle(0), muted(1), normal(2), highlight(3), accent(4)
        self.pair_ids = list(range(TELEGRAM_PAIR_BASE, TELEGRAM_PAIR_BASE + 5))

    def get(self, index: int) -> int:
        return self.pair_ids[index % len(self.pair_ids)]

    def __len__(self) -> int:
        return len(self.pair_ids)

    @staticmethod
    def init_colors():
        """Initialize curses color pairs. Call after curses.start_color()."""
        import curses

        colors = [
            TELEGRAM_COLORS["subtle"],
            TELEGRAM_COLORS["muted"],
            TELEGRAM_COLORS["normal"],
            TELEGRAM_COLORS["highlight"],
            TELEGRAM_COLORS["accent"],
        ]
        for i, fg in enumerate(colors):
            curses.init_pair(TELEGRAM_PAIR_BASE + i, fg, -1)
