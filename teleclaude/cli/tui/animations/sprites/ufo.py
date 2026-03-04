"""UFO sky entity sprite — layered with per-layer color."""

from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteLayer

# fmt: off
UFO_SPRITE = CompositeSprite(
    z_weights=[(30, 10), (70, 90)],
    y_weights=[(0, 30), (1, 50), (2, 20)],
    speed_weights=[(0, 10), (0.3, 20), (0.4, 20), (0.5, 20), (0.7, 10)],
    layers=[
        SpriteLayer(
            positive=[
                "     ◢▇◣     ",
                "◖███████████◗",
                "    ◥ █ ◤    ",
            ],
            negative=[
                "             ",
                "             ",
                "     █ █     ",
            ],
            # negative=[
            #     "             ",
            #     "  ● ● ● ● ●  ",
            #     "             ",
            # ],
            color="#dddddd",
        ),
        SpriteLayer(
            positive=[
                "    ◢   ◣    ",
                "             ",
                "    ◥ █ ◤    ",
            ],
            negative=[
                "     ◢▇◣     ",
                "  █ █ █ █ █  ",
                "     ◆ ◆     ",
            ],
            color="#999999",
        ),
        SpriteLayer(
            positive=[
                "             ",
                "◖ ● ● ● ● ● ◗",
                "     ◆ ◆     ",
            ],
            color="#FFD700",
        ),
    ],
)
# fmt: on
