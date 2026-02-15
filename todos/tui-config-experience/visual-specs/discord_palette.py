"""Discord 'Blurple Pulse' section palette — xterm-256 color definitions.

Creative direction: Gaming lounge energy. Discord's signature blurple as the
anchor, flanked by deep purple (rest) and light purple (energy). Light lavender
accent for celebration/success (keeps in purple family), red for errors.

Terminal requirement: TERM=xterm-256color for full palette.
Phase 2 registers these via curses.init_pair(pair_id, fg, bg=-1).
"""

from teleclaude.cli.tui.animation_colors import ColorPalette

# xterm-256 source of truth
# NOTE: accent uses lavender (189) instead of gold — gold (220) belongs to AI Keys
DISCORD_COLORS = {
    "subtle": 55,  # dark purple — deep rest state
    "muted": 62,  # medium slate blue — default idle
    "normal": 63,  # blurple — Discord's #5865F2
    "highlight": 141,  # light purple — energy/emphasis
    "accent_lavender": 189,  # light lavender — celebration/success
    "accent_red": 203,  # light red — Discord's #ED4245 / error
}

# Pair ID range: 61-66
DISCORD_PAIR_BASE = 61


class DiscordPalette(ColorPalette):
    """Discord section palette: 6 colors from deep purple to highlight + accents."""

    def __init__(self):
        super().__init__("discord")
        # Ordered: subtle(0), muted(1), normal(2), highlight(3), accent_lavender(4), accent_red(5)
        self.pair_ids = list(range(DISCORD_PAIR_BASE, DISCORD_PAIR_BASE + 6))

    def get(self, index: int) -> int:
        return self.pair_ids[index % len(self.pair_ids)]

    def __len__(self) -> int:
        return len(self.pair_ids)

    @staticmethod
    def init_colors():
        """Initialize curses color pairs. Call after curses.start_color()."""
        import curses

        colors = [
            DISCORD_COLORS["subtle"],
            DISCORD_COLORS["muted"],
            DISCORD_COLORS["normal"],
            DISCORD_COLORS["highlight"],
            DISCORD_COLORS["accent_lavender"],
            DISCORD_COLORS["accent_red"],
        ]
        for i, fg in enumerate(colors):
            curses.init_pair(DISCORD_PAIR_BASE + i, fg, -1)
