"""WhatsApp 'Message Bubble' section palette — xterm-256 color definitions.

Creative direction: WhatsApp's teal-green identity, pushed warmer than
Environment's forest greens to maintain clear visual separation. From dark
teal (rest) through cyan-green (active) to bright aquamarine (highlight).
Blue accent evokes the "read" receipt double-check mark.

Terminal requirement: TERM=xterm-256color for full palette.
Phase 2 registers these via curses.init_pair(pair_id, fg, bg=-1).
"""

from teleclaude.cli.tui.animation_colors import ColorPalette

# xterm-256 source of truth
# NOTE: Intentionally teal-shifted vs Environment's forest greens (22/28/34/46)
WHATSAPP_COLORS = {
    "subtle": 23,  # dark teal — deep rest
    "muted": 30,  # teal — default idle
    "normal": 36,  # dark cyan — active
    "highlight": 49,  # bright aquamarine — WhatsApp's teal identity
    "accent": 75,  # sky blue — "read" receipt blue
}

# Pair ID range: 67-71
WHATSAPP_PAIR_BASE = 67


class WhatsAppPalette(ColorPalette):
    """WhatsApp section palette: 5 colors from dark green to spring green + blue accent."""

    def __init__(self):
        super().__init__("whatsapp")
        self.pair_ids = list(range(WHATSAPP_PAIR_BASE, WHATSAPP_PAIR_BASE + 5))

    def get(self, index: int) -> int:
        return self.pair_ids[index % len(self.pair_ids)]

    def __len__(self) -> int:
        return len(self.pair_ids)

    @staticmethod
    def init_colors():
        """Initialize curses color pairs. Call after curses.start_color()."""
        import curses

        colors = [
            WHATSAPP_COLORS["subtle"],
            WHATSAPP_COLORS["muted"],
            WHATSAPP_COLORS["normal"],
            WHATSAPP_COLORS["highlight"],
            WHATSAPP_COLORS["accent"],
        ]
        for i, fg in enumerate(colors):
            curses.init_pair(WHATSAPP_PAIR_BASE + i, fg, -1)
