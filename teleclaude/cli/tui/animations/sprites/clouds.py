"""Cloud sprite definitions for TUI sky animations.

Sprites grouped by visual depth: far (wisps), mid (puffs/medium), near (cumulus).
Uses shade block characters for consistent visual style:
  ░ (U+2591) = light shade, ▒ (U+2592) = medium shade, ▓ (U+2593) = dark shade.
"""

# Far clouds — thin wisps (1 row each)
CLOUD_SPRITES_FAR: list[list[str]] = [
    [" ━━━━━━━━"],
    ["━━━━━━━━━━━━"],
    [" ━━━━━━━━━━━━━━━   "],
    ["   ━━━━━━━━━━━━━━━ "],
    ["─────────"],
    ["─ ─ ─ ─ ─ ─"],
]

# Mid clouds — puffs and medium shapes (2-3 rows)
CLOUD_SPRITES_MID: list[list[str]] = [
    [
        "        ░░▒▒▓▓██▓▓▒▒░░       ",
        "   ░░▒▒▓▓███▓▓▒▒░░▒▒▓▓█▓▓▒▒░░",
        "░▒▒▓█▓▒▒░                    ",
    ],
    [
        "      ░▒▒▓█▓▒▒░.   ░▒▒░░░▒▒▒▒░ ",
        "░░▒▒▓▓████▓▓▒▒░░▒▒▓▓▒░         ",
    ],
    ["░░░", "░░░░░", "░░░░"],
]

# Near clouds — large cumulus (4+ rows, dense centers)
CLOUD_SPRITES_NEAR: list[list[str]] = [
    [
        "    ░░░░░░░░           ",
        "  ░░▒▒████▒▒░░ ░░▒██▒▒░░       ",
        "░▒▒▓███████████████████▒▒░          ",
        "░░▒▒▒▓▓███████████████▒▒░        ",
    ],
    [
        "   ░░░░░░░░░   ",
        " ░░▒▒▒▒▒▒▒▒░░  ",
        "░░▒▒▒▒▒▒▒▒▒▒░░ ",
        " ░░░░▒▒▒▒░░░   ",
    ],
]
