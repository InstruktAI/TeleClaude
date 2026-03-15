"""Characterization tests for animations/sprites/clouds.py."""

from __future__ import annotations

from teleclaude.cli.tui.animations.sprites.clouds import (
    CLOUD_MEDIUM_1,
    CLOUD_MEDIUM_2,
    CLOUDS_CLEAR,
    CLOUDS_CLOUDY,
    CLOUDS_FAIR,
    CLOUDS_OVERCAST,
    CUMULUS_1,
    CUMULUS_2,
    PUFF_1,
    PUFF_2,
    PUFF_3,
    WISP_1,
    WISP_2,
    WISP_3,
    WISP_4,
    WISP_5,
    WISP_6,
)
from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteGroup


class TestWisps:
    def test_all_wisps_are_composite_sprites(self) -> None:
        for wisp in (WISP_1, WISP_2, WISP_3, WISP_4, WISP_5, WISP_6):
            assert isinstance(wisp, CompositeSprite)

    def test_wisp_1_has_single_layer(self) -> None:
        assert len(WISP_1.layers) == 1

    def test_wisp_z_weights_present(self) -> None:
        for wisp in (WISP_1, WISP_2, WISP_3, WISP_4):
            assert len(wisp.z_weights) > 0

    def test_wisps_have_slow_speed(self) -> None:
        # Wisps should be slow (max speed <= 0.2)
        for wisp in (WISP_1, WISP_2, WISP_3):
            speeds = [abs(s) for s, _ in wisp.speed_weights]
            assert max(speeds) <= 0.2


class TestPuffs:
    def test_puff_1_is_composite_sprite(self) -> None:
        assert isinstance(PUFF_1, CompositeSprite)

    def test_puff_2_is_composite_sprite(self) -> None:
        assert isinstance(PUFF_2, CompositeSprite)

    def test_puff_3_has_3_rows(self) -> None:
        layer = PUFF_3.layers[0]
        assert len(layer.positive) == 3

    def test_puffs_have_z_weights(self) -> None:
        for puff in (PUFF_1, PUFF_2, PUFF_3):
            assert len(puff.z_weights) > 0


class TestMediumClouds:
    def test_cloud_medium_1_is_composite(self) -> None:
        assert isinstance(CLOUD_MEDIUM_1, CompositeSprite)

    def test_cloud_medium_2_has_3_rows(self) -> None:
        layer = CLOUD_MEDIUM_2.layers[0]
        assert len(layer.positive) == 3

    def test_medium_speed_range(self) -> None:
        for cloud in (CLOUD_MEDIUM_1, CLOUD_MEDIUM_2):
            speeds = [s for s, _ in cloud.speed_weights]
            assert max(speeds) <= 0.5


class TestCumulusClouds:
    def test_cumulus_1_is_composite(self) -> None:
        assert isinstance(CUMULUS_1, CompositeSprite)

    def test_cumulus_2_has_4_rows(self) -> None:
        layer = CUMULUS_2.layers[0]
        assert len(layer.positive) == 4

    def test_cumulus_faster_than_medium(self) -> None:
        cumulus_max = max(s for s, _ in CUMULUS_1.speed_weights)
        medium_max = max(s for s, _ in CLOUD_MEDIUM_1.speed_weights)
        assert cumulus_max > medium_max


class TestCloudGroups:
    def test_clouds_clear_is_sprite_group(self) -> None:
        assert isinstance(CLOUDS_CLEAR, SpriteGroup)

    def test_clouds_fair_is_sprite_group(self) -> None:
        assert isinstance(CLOUDS_FAIR, SpriteGroup)

    def test_clouds_cloudy_is_sprite_group(self) -> None:
        assert isinstance(CLOUDS_CLOUDY, SpriteGroup)

    def test_clouds_overcast_is_sprite_group(self) -> None:
        assert isinstance(CLOUDS_OVERCAST, SpriteGroup)

    def test_all_groups_weights_sum_to_one(self) -> None:
        for group in (CLOUDS_CLEAR, CLOUDS_FAIR, CLOUDS_CLOUDY, CLOUDS_OVERCAST):
            total = sum(w for _, w, _ in group.entries)
            assert abs(total - 1.0) < 1e-6, f"Group {group} weights sum to {total}"

    def test_clear_has_only_wisps(self) -> None:
        sprites = [s for s, _, _ in CLOUDS_CLEAR.entries]
        wisps = [WISP_1, WISP_2, WISP_3, WISP_4, WISP_5, WISP_6]
        assert all(s in wisps for s in sprites)

    def test_overcast_has_cumulus(self) -> None:
        sprites = [s for s, _, _ in CLOUDS_OVERCAST.entries]
        assert CUMULUS_1 in sprites or CUMULUS_2 in sprites

    def test_group_direction_none(self) -> None:
        for group in (CLOUDS_CLEAR, CLOUDS_FAIR, CLOUDS_CLOUDY, CLOUDS_OVERCAST):
            assert group.direction is None
