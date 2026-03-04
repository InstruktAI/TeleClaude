"""Bird sprites -- animated flapping with two-frame cycle."""

from teleclaude.cli.tui.animations.sprites.composite import AnimatedSprite, CompositeSprite, SpriteGroup, SpriteLayer

# fmt: off
BIRD_SMALL = AnimatedSprite(
    frames=[["v"], ["^"]],
    z_weights=[(29, 40), (39, 60)],
    y_weights=[(0, 50), (1, 40), (2, 10)],
    speed_weights=[(0.2, 20), (0.3, 40), (0.5, 30), (0.8, 10)],
)

# BIRD_MEDIUM = AnimatedSprite(
#     frames=[[
#         "◝◜"
#     ], [
#         "◜◝",
#     ]],
#     z_weights=[(49, 50), (59, 50)],
#     y_weights=[(0, 20), (1, 20), (2, 20)],
#     speed_weights=[(0.8, 20), (1.1, 40), (1.4, 30), (1.8, 10)],
# )

BIRD_LARGE = AnimatedSprite(
    frames=[
        CompositeSprite(layers=[SpriteLayer(
            positive=[
            "◥◣◢◤",
            "    ",
            "    ",
        ]), SpriteLayer(
            color="#dddddd",
            positive=[
            "    ",
            " ▝▘ ",
            "    ",
        ],
        )]),
        CompositeSprite(layers=[SpriteLayer(
            positive=[
            "    ",
            "    ",
            "◢◤◥◣",
        ]), SpriteLayer(
            color="#dddddd",
            positive=[
            "    ",
            " ▗▖ ",
            "    ",
        ])]),
    ],
    z_weights=[(49, 50), (59, 50)],
    y_weights=[(0, 20), (1, 20), (2, 20)],
    speed_weights=[(0.7, 20), (0.8, 40), (1.0, 30), (1.2, 10)],
)

BIRD_FLOCK = SpriteGroup(
    entries=[
        (BIRD_SMALL,  0.85, (9, 26)),
        # (BIRD_MEDIUM, 0.3, (3, 9)),
        (BIRD_LARGE, 0.15, (1, 3)),
    ],
)
# fmt: on
