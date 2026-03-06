"""UFO sky entity sprite — layered with per-layer color."""

from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteGroup, SpriteLayer

# fmt: off
UFO_SPRITE_1 = CompositeSprite(
    z_weights=[(30, 10), (40, 50), (51, 10), (61, 10), (79, 10), (81, 10)],
    y_weights=[(0, 7, 100)],
    speed_weights=[(0, 5), (0.3, 10), (0.7, 10), (1.2, 10), (1.5, 10), (2, 10), (-0.3, 10), (-0.7, 10), (-1.2, 10), (-1.5, 10), (-2, 5)],
    layers=[
        SpriteLayer(
            positive=[
                "    ◢◤ ◥◣    ",
                " ▇█████████▇ ",
                "    ◥◣ ◢◤    ",
            ],
            negative=[
                "             ",
                "             ",
                "             ",
            ],
            color="#bbbbbb",
        ),
        SpriteLayer(
            positive=[
                "     ◢█◣     ",
                "             ",
                "     ◥█◤     ",
            ],
            negative=[
                "             ",
                "             ",
                "             ",
            ],
            color="#999999",
        ),
        SpriteLayer(
            positive=[
                "             ",
                "◖ ● ● ● ● ● ◗",
                "             ",
            ],
            color="#ffffff",
        ),
    ],
)

# UFO_SPRITE_2 = replace(UFO_SPRITE_1,
#     z_weights=[(79, 50), (81, 50)], y_weights=[(7, 7, 100)]
# )

# UFO_SPRITE = SpriteGroup(entries=[(UFO_SPRITE_1, 0, (1, 2)), (UFO_SPRITE_2, 1, (1, 1))])
UFO_SPRITE = SpriteGroup(entries=[(UFO_SPRITE_1, 1, (0, 1))])
# fmt: on
