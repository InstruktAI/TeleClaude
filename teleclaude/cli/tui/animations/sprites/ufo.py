"""UFO sky entity sprite — layered with per-layer color."""

from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteLayer

# fmt: off
UFO_SPRITE = CompositeSprite(
    z_weights=[(30, 10), (81, 90)],
    y_weights=[(0, 30), (1, 40), (2, 30)],
    speed_weights=[(0, 10), (0.3, 20), (0.4, 20), (1, 20), (0.7, 10)],
    layers=[
        SpriteLayer(
            positive=[
                "      ▁      ",
                "    ◢◤ ◥◣    ",
                " ▇█████████▇ ",
                "    ◥◣ ◢◤    ",
                "             ",
            ],
            negative=[
                "             ",
                "             ",
                "             ",
                "             ",
                "      ▇      ",
            ],
            color="#bbbbbb",
        ),
        SpriteLayer(
            positive=[
                "             ",
                "     ◢█◣     ",
                "             ",
                "     ◥█◤     ",
                "            ",
            ],
            negative=[
                "             ",
                "             ",
                "             ",
                "             ",
                "             ",
            ],
            color="#999999",
        ),
        SpriteLayer(
            positive=[
                "             ",
                "             ",
                "◖ ● ● ● ● ● ◗",
                "             ",
                "             ",
            ],
            color="#ffffff",
        ),
    ],
)
# fmt: on
