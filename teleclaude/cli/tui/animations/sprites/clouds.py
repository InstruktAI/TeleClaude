"""Cloud sprite definitions for TUI sky animations.

Uses shade block characters for visual depth:
  ░ (U+2591) = light shade, ▒ (U+2592) = medium shade, ▓ (U+2593) = dark shade.

Each cloud is a CompositeSprite with z_weights, y_weights, and speed_weights
so the engine spawns and renders them like any other sky entity.
"""

from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteGroup, SpriteLayer

# fmt: off

# --- Wisps (1 row, slow, mostly far) ---

WISP_1 = CompositeSprite(
    layers=[SpriteLayer(positive=["━━━━━━"])],
    z_weights=[(30, 60), (50, 30), (70, 10)],
    y_weights=[(0, 40), (1, 40), (2, 20)],
    speed_weights=[(0.08, 30), (0.12, 40), (0.18, 30)],
    # theme="light",
)
WISP_2 = CompositeSprite(
    layers=[SpriteLayer(positive=["━━━━━━━━━"])],
    z_weights=[(30, 60), (50, 30), (70, 10)],
    y_weights=[(0, 40), (1, 40), (2, 20)],
    speed_weights=[(0.08, 30), (0.12, 40), (0.18, 30)],
    # theme="light",
)
WISP_3 = CompositeSprite(
    layers=[SpriteLayer(positive=["━━━━━━━━━━━━━"])],
    z_weights=[(30, 60), (50, 30), (70, 10)],
    y_weights=[(0, 40), (1, 40), (2, 20)],
    speed_weights=[(0.08, 30), (0.12, 40), (0.18, 30)],
    # theme="light",
)
WISP_4 = CompositeSprite(
    layers=[SpriteLayer(positive=["━━━━━━━ ━━━━━━━━"])],
    z_weights=[(30, 60), (50, 30), (70, 10)],
    y_weights=[(0, 40), (1, 40), (2, 20)],
    speed_weights=[(0.08, 30), (0.12, 40), (0.18, 30)],
    # theme="light",
)
WISP_5 = CompositeSprite(
    layers=[SpriteLayer(positive=["─────────"])],
    z_weights=[(30, 60), (50, 30), (70, 10)],
    y_weights=[(0, 40), (1, 40), (2, 20)],
    speed_weights=[(0.08, 30), (0.12, 40), (0.18, 30)],
    # theme="light",
)
WISP_6 = CompositeSprite(
    layers=[SpriteLayer(positive=["─────────"])],
    z_weights=[(30, 60), (50, 30), (70, 10)],
    y_weights=[(0, 40), (1, 40), (2, 20)],
    speed_weights=[(0.08, 30), (0.12, 40), (0.18, 30)],
    # theme="light",
)

# --- Puffs (slow-medium, far/mid) ---

PUFF_1 = CompositeSprite(
    layers=[SpriteLayer(positive=[
        "░░░░░░░",
    ])],
    z_weights=[(30, 50), (50, 40), (70, 10)],
    y_weights=[(0, 30), (1, 40), (2, 30)],
    speed_weights=[(0.15, 30), (0.22, 40), (0.30, 30)],
    # theme="light",
)

PUFF_2 = CompositeSprite(
    layers=[SpriteLayer(positive=[
        "   ░░░░░",
        "░░░░░   "
    ])],
    z_weights=[(30, 50), (50, 40), (70, 10)],
    y_weights=[(0, 30), (1, 40), (2, 30)],
    speed_weights=[(0.15, 30), (0.22, 40), (0.30, 30)],
    # theme="light",
)

PUFF_3 = CompositeSprite(
    layers=[SpriteLayer(positive=[
        "  ░░░   ",
        " ░░░░░░░",
        "   ░░░░ "
    ])],
    z_weights=[(30, 50), (50, 40), (70, 10)],
    y_weights=[(0, 30), (1, 40), (2, 30)],
    speed_weights=[(0.15, 30), (0.22, 40), (0.30, 30)],
    # theme="light",
)

# --- Medium (2 rows, medium speed, mostly mid) ---

CLOUD_MEDIUM_1 = CompositeSprite(
    layers=[SpriteLayer(positive=[
        "      ░▒▒▓▇▓▒▒░.   ░▒▒░░░▒▒▒▒░ ",
        "░░▒▒▓▓▇▇▇▇▓▓▒▒░░▒▒▓▓▒░         ",
    ])],
    z_weights=[(30, 50), (50, 40), (70, 10)],
    y_weights=[(0, 30), (1, 40), (2, 30)],
    speed_weights=[(0.15, 30), (0.22, 40), (0.30, 30)],
    # theme="light",
)

# --- Medium (3 rows, medium speed, mostly mid) ---

CLOUD_MEDIUM_2 = CompositeSprite(
    layers=[SpriteLayer(positive=[
        "        ░░▒▒▓▓▇▇▓▓▒▒░░       ",
        "   ░░▒▒▓▓▇▇▇▓▓▒▒░░▒▒▓▓▇▓▓▒▒░░",
        "░▒▒▓▇▓▒▒░                    ",
    ])],
    z_weights=[(30, 40), (50, 55), (70, 5)],
    y_weights=[(0, 20), (1, 50), (2, 30)],
    speed_weights=[(0.25, 30), (0.35, 40), (0.45, 30)],
    # theme="light",
)

# --- Cumulus (4+ rows, fast, close, NEVER near Z) ---

CUMULUS_1 = CompositeSprite(
    layers=[SpriteLayer(positive=[
        "    ░░░░░░░░           ",
        "  ░░▒▒▇▇▇▇▒▒░░ ░░▒▇▇▒▒░░       ",
        "░▒▒▓▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▒▒░          ",
        "░░▒▒▒▓▓▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▒▒░        ",
    ])],
    z_weights=[(30, 70), (50, 30)],
    y_weights=[(0, 20), (1, 50), (2, 30)],
    speed_weights=[(0.40, 30), (0.52, 40), (0.65, 30)],
    # theme="light",
)
CUMULUS_2 = CompositeSprite(
    layers=[SpriteLayer(positive=[
        "   ░░░▒▒▒▒░░░   ",
        " ░░▒▒▒▇▇▇▇▇▇▒▒░░  ",
        "░░▒▒▒▇▇▇▇▇▇▇▇▇▒▒▒░░ ",
        " ░░░░▒▇▇▇▇▇▇▒▒░░░   ",
    ])],
    z_weights=[(30, 70), (50, 30)],
    y_weights=[(0, 20), (1, 50), (2, 30)],
    speed_weights=[(0.40, 30), (0.52, 40), (0.65, 30)],
    # theme="light",
)

# --- Cloud groups (weather patterns) ---

CLOUDS_CLEAR = SpriteGroup(
    entries=[
        (WISP_1, 0.17, (1, 2)),
        (WISP_2, 0.17, (1, 2)),
        (WISP_3, 0.17, (0, 1)),
        (WISP_4, 0.17, (0, 1)),
        (WISP_5, 0.16, (0, 1)),
        (WISP_6, 0.16, (0, 1)),
    ],
)

CLOUDS_FAIR = SpriteGroup(
    entries=[
        (WISP_1, 0.12, (0, 1)),
        (WISP_2, 0.12, (0, 1)),
        (WISP_3, 0.12, (0, 1)),
        (WISP_4, 0.12, (0, 1)),
        (WISP_5, 0.10, (1, 2)),
        (WISP_6, 0.10, (1, 2)),
        (CLOUD_MEDIUM_1, 0.16, (1, 2)),
        (PUFF_1, 0.07, (1, 2)),
        (PUFF_2, 0.05, (1, 2)),
        (PUFF_3, 0.04, (1, 2)),
    ],
)

CLOUDS_CLOUDY = SpriteGroup(
    entries=[
        (WISP_1, 0.01, (0, 1)),
        (WISP_2, 0.02, (0, 1)),
        (WISP_3, 0.03, (0, 1)),
        (WISP_4, 0.04, (0, 1)),
        (WISP_5, 0.04, (1, 2)),
        (WISP_6, 0.04, (1, 2)),
        (PUFF_3, 0.20, (1, 3)),
        (CLOUD_MEDIUM_1, 0.42, (1, 3)),
        (CLOUD_MEDIUM_2, 0.20, (1, 2)),
    ],
)

CLOUDS_OVERCAST = SpriteGroup(
    entries=[
        (WISP_5, 0.02, (1, 2)),
        (WISP_6, 0.03, (1, 2)),
        (PUFF_3, 0.10, (2, 3)),
        (CLOUD_MEDIUM_1, 0.10, (2, 3)),
        (CLOUD_MEDIUM_2, 0.25, (3, 5)),
        (CUMULUS_1, 0.30, (1, 2)),
        (CUMULUS_2, 0.20, (1, 3)),
    ],
)
# fmt: on
