"""Validate 'The Scan' section palette — xterm-256 color definitions.

Creative direction: Clinical, diagnostic. Uses the existing SpectrumPalette
for the scanning beam (rainbow), plus dedicated success green, failure red,
and gold settle colors. The scanner sees everything — all colors.

Terminal requirement: TERM=xterm-256color for full palette.
Phase 2 registers these via curses.init_pair(pair_id, fg, bg=-1).

Note: This palette SUPPLEMENTS the SpectrumPalette (pairs 30-36) which
provides the rainbow colors for the scanning beam. The 3 colors below
are for state feedback (success/error/settle).
"""

from teleclaude.cli.tui.animation_colors import ColorPalette

# xterm-256 source of truth (supplements SpectrumPalette pairs 30-36)
VALIDATE_COLORS = {
    "success": 46,  # bright green — validation pass
    "failure": 196,  # red — validation fail
    "settle": 220,  # gold — post-celebration settle
}

# Pair ID range: 89-91 (prototype allocation, Phase 2 formalizes)
VALIDATE_PAIR_BASE = 89


class ValidatePalette(ColorPalette):
    """Validate section palette: 3 state colors + SpectrumPalette for beam.

    Indices 0=success_green, 1=failure_red, 2=settle_gold.
    For spectrum/beam colors, animations reference palette_registry.get("spectrum").
    """

    def __init__(self):
        super().__init__("validate")
        # Ordered: success_green(0), failure_red(1), settle_gold(2)
        self.pair_ids = list(range(VALIDATE_PAIR_BASE, VALIDATE_PAIR_BASE + 3))

    def get(self, index: int) -> int:
        return self.pair_ids[index % len(self.pair_ids)]

    def __len__(self) -> int:
        return len(self.pair_ids)

    @staticmethod
    def init_colors():
        """Initialize curses color pairs. Call after curses.start_color()."""
        import curses

        colors = [
            VALIDATE_COLORS["success"],
            VALIDATE_COLORS["failure"],
            VALIDATE_COLORS["settle"],
        ]
        for i, fg in enumerate(colors):
            curses.init_pair(VALIDATE_PAIR_BASE + i, fg, -1)
