"""Car entity sprite — drives along the tab bar connector line."""

from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteGroup, SpriteLayer

_CAR_COLORS = ["#E12A1D", "#0040FF", "#A333FF", "#FF9500", "#00C8C8", "#F6E100"]
_HEAD_COLORS = ["#E2C400", "#CD8900", "#FFE2D8", "#000000"]
_SHOULDER_COLORS = _CAR_COLORS

_WHEEL_COLOR = "#EAEAEA"
# fmt: off
CAR_SPRITE_LEFT = CompositeSprite(
    z_weights=[(71, 25), (73, 25), (75, 25), (77, 25)],
    y_weights=[(7, 7, 100)],
    speed_weights=[(-0.5, 10), (-0.7, 10), (-0.9, 20), (-1.1, 30), (-1.3, 20), (-1.5, 10)],
    layers=[
        SpriteLayer( # car body
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
            color=_CAR_COLORS,
        ),
        SpriteLayer( # head
            positive=[
                "        ▇        ",
                "                 ",
                "                 ",
            ],
            color=_HEAD_COLORS,
        ),
        SpriteLayer( # shoulders
            negative=[
                "                 ",
                "        ▆        ",
                "                 ",
            ],
            color=_SHOULDER_COLORS,
        ),
        SpriteLayer( # wheel caps
            positive=[
                "                ",
                "                 ",
                "   █         █   ",
            ],
            color=_WHEEL_COLOR,
        ),
        SpriteLayer( # tyres
            positive=[
                "                 ",
                "                 ",
                "  ▚▂▞       ▚▂▞  ",
            ],
            color="#000000",
        ),
    ],
)
CAR_SPRITE_RIGHT = CompositeSprite(
    z_weights=[(72, 25), (74, 25), (76, 25), (78, 25)],
    y_weights=[(7, 7, 100)],
    speed_weights=[(0.5, 10), (0.7, 10), (0.9, 20), (1.1, 30), (1.3, 20), (1.5, 10)],
    layers=[  
        SpriteLayer( # car body
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
            color=_CAR_COLORS,
        ),
        SpriteLayer( # head
            positive=[
                "        ▇        ",
                "                 ",
                "                 ",
            ],
            color=_HEAD_COLORS,
        ),
        SpriteLayer( # shoulders
            negative=[
                "                 ",
                "        ▆        ",
                "                 ",
            ],
            color=_SHOULDER_COLORS,
        ),
        SpriteLayer( # wheel caps
            positive=[
                "                 ",
                "                 ",
                "   █         █   ",
            ],
            color=_WHEEL_COLOR,
        ),
        SpriteLayer( # tyres
            positive=[
                "                 ",
                "                 ",
                "  ▚▂▞       ▚▂▞  ",
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
