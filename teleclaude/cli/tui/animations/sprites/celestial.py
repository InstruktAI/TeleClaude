"""Sun/Moon celestial sprite — full disc with inverted bottom half.

Top half: standard lower-block chars (positive layer).
Bottom half: complement lower-block chars (negative layer) with quadrant
chars and full blocks in the positive layer (they render correctly without
inversion).
"""

from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteLayer

# fmt: off
MOON_SPRITE = CompositeSprite(
    layers=[
        SpriteLayer(
            positive=[
                "  ▁▄▆▇███▇▆▄▁  ",
                " ▅███████████▅ ",
                "▟█████████████▙",
                "▜█████████████▛",
                "               ",
                "               ",
            ],
            negative=[
                "               ",
                "               ",
                "               ",
                "               ",
                " ▃███████████▃ ",
                "  ▇▄▂▁███▁▂▄▇  ",
            ],
            color="#FFFFFF",
        ),
    ],
)
SUN_SPRITE = CompositeSprite(
    layers=[MOON_SPRITE.layers[0]._replace(color="#FFD700")],
)
# fmt: on
