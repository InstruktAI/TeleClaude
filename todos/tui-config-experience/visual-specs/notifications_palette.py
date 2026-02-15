"""Notifications 'Bell Sway' section palette — xterm-256 color definitions.

Creative direction: Electric cyan with gold bell accent. The feel of an
alert — crisp, attention-grabbing, but not alarming. Cyan for the digital
signal, gold for the bell's warmth.

Terminal requirement: TERM=xterm-256color for full palette.
Phase 2 registers these via curses.init_pair(pair_id, fg, bg=-1).
"""

from teleclaude.cli.tui.animation_colors import ColorPalette

# xterm-256 source of truth
NOTIFICATIONS_COLORS = {
    "subtle": 23,  # dark cyan — deep background
    "muted": 37,  # medium cyan — resting state
    "normal": 51,  # cyan/electric — active signal
    "highlight": 220,  # gold/yellow — bell accent
    "accent": 231,  # white — flash peak
    "accent_2": 167,  # red — error/muted bell
}

# Pair ID range: 77-82 (prototype allocation, Phase 2 formalizes)
NOTIFICATIONS_PAIR_BASE = 77


class NotificationsPalette(ColorPalette):
    """Notifications section palette: 6 colors — cyan spectrum + gold + red."""

    def __init__(self):
        super().__init__("notifications")
        # Ordered: subtle(0), muted(1), normal(2), highlight/gold(3), accent/white(4), accent_red(5)
        self.pair_ids = list(range(NOTIFICATIONS_PAIR_BASE, NOTIFICATIONS_PAIR_BASE + 6))

    def get(self, index: int) -> int:
        return self.pair_ids[index % len(self.pair_ids)]

    def __len__(self) -> int:
        return len(self.pair_ids)

    @staticmethod
    def init_colors():
        """Initialize curses color pairs. Call after curses.start_color()."""
        import curses

        colors = [
            NOTIFICATIONS_COLORS["subtle"],
            NOTIFICATIONS_COLORS["muted"],
            NOTIFICATIONS_COLORS["normal"],
            NOTIFICATIONS_COLORS["highlight"],
            NOTIFICATIONS_COLORS["accent"],
            NOTIFICATIONS_COLORS["accent_2"],
        ]
        for i, fg in enumerate(colors):
            curses.init_pair(NOTIFICATIONS_PAIR_BASE + i, fg, -1)
