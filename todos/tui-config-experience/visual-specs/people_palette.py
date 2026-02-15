"""People 'Heartbeat' section palette — xterm-256 color definitions.

Creative direction: Warm human tones. Dusty rose through salmon to gold.
The feeling of community, connection, warmth. The heartbeat of the team.

Terminal requirement: TERM=xterm-256color for full palette.
Phase 2 registers these via curses.init_pair(pair_id, fg, bg=-1).
"""

from teleclaude.cli.tui.animation_colors import ColorPalette

# xterm-256 source of truth
PEOPLE_COLORS = {
    "subtle": 95,  # dusty rose — deep background
    "muted": 131,  # indian red — resting heartbeat
    "normal": 174,  # light pink/salmon — active pulse
    "highlight": 210,  # light salmon — peak beat
    "accent": 220,  # gold — celebration/success
}

# Pair ID range: 72-76 (prototype allocation, Phase 2 formalizes)
PEOPLE_PAIR_BASE = 72


class PeoplePalette(ColorPalette):
    """People section palette: 5 colors from dusty rose to gold."""

    def __init__(self):
        super().__init__("people")
        # Ordered: subtle(0), muted(1), normal(2), highlight(3), accent(4)
        self.pair_ids = list(range(PEOPLE_PAIR_BASE, PEOPLE_PAIR_BASE + 5))

    def get(self, index: int) -> int:
        return self.pair_ids[index % len(self.pair_ids)]

    def __len__(self) -> int:
        return len(self.pair_ids)

    @staticmethod
    def init_colors():
        """Initialize curses color pairs. Call after curses.start_color()."""
        import curses

        colors = [
            PEOPLE_COLORS["subtle"],
            PEOPLE_COLORS["muted"],
            PEOPLE_COLORS["normal"],
            PEOPLE_COLORS["highlight"],
            PEOPLE_COLORS["accent"],
        ]
        for i, fg in enumerate(colors):
            curses.init_pair(PEOPLE_PAIR_BASE + i, fg, -1)
