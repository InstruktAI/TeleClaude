"""Car entity sprite — drives along the tab bar connector line."""

from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteGroup, SpriteLayer

# fmt: off
CAR_SPRITE_LEFT = CompositeSprite(
    z_weights=[(75, 100)],
    y_weights=[(7, 7, 100)],
    speed_weights=[(-0.3, 10), (-0.5, 10), (-0.7, 20), (-0.9, 30), (-1.1, 20), (-1.2, 10)],
    layers=[
        SpriteLayer(
            positive=[
                "    ▁╱  █ █   ▎  ",
                "▆▇███▆▆▆▆▆█▆▆▆██▇",
                "                 ",
            ],
            negative=[
                "      ▇▇ ▇ ▇▇▇   ",
                "                 ",
                "▅▅   ▅▅▅▅▅▅▅   ▅▅",
            ],
            color="#E12A1D",
        ),
        SpriteLayer(
            positive=[
                "                 ",
                "                 ",
                "                 ",
            ],
            color="#C48507FF",
        ),
        SpriteLayer(
            positive=[
                "        ▇        ",
                "                 ",
                "   █         █   ",
            ],
            color="#FFD700",
        ),
        SpriteLayer(
            positive=[
                "                 ",
                "                 ",
                "  ▚▂▞       ▚▂▞  ",
            ],
            negative=[
                "                 ",
                "        ▆        ",
                "                 ",
            ],
            color="#000000",
        ),
    ],
)
CAR_SPRITE_RIGHT = CompositeSprite(
    z_weights=[(76, 100)],
    y_weights=[(7, 7, 100)],
    speed_weights=[(0.3, 10), (0.5, 10), (0.7, 20), (0.9, 30), (1.1, 20), (1.2, 10)],
    layers=[  
        SpriteLayer(
            positive=[
                "      █ █  ╲▁    ",
                "▇██▆▆▆█▆▆▆▆▆███▇▆",
                "                 ",
            ],
            negative=[
                "  ▊▇▇▇ ▇ ▇▇      ",
                "                 ",
                "▅▅   ▅▅▅▅▅▅▅   ▅▅",
            ],
            color="#E12A1D",
        ),
        SpriteLayer(
            positive=[
                "        ▇        ",
                "                 ",
                "   █         █   ",
            ],
            color="#FFD700",
        ),
        SpriteLayer(
            positive=[
                "                 ",
                "                 ",
                "  ▚▂▞       ▚▂▞  ",
            ],
            negative=[
                "                 ",
                "        ▆        ",
                "                 ",
            ],
            color="#000000",
        ),
    ],
)

CAR_SPRITE = SpriteGroup(
    entries=[
        (CAR_SPRITE_LEFT, 0.5, (1, 1)),
        (CAR_SPRITE_RIGHT, 0.5, (1, 1)),
    ],
    direction=None,
)

# fmt: on
