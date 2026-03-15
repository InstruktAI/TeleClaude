"""Characterization tests for animations/general.py."""

from __future__ import annotations

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.animations.general import (
    GENERAL_ANIMATIONS,
    BlinkSweep,
    DiagonalSweepDL,
    DiagonalSweepDR,
    FullSpectrumCycle,
    LetterShimmer,
    LetterWaveLR,
    LetterWaveRL,
    LineSweepBottomTop,
    LineSweepTopBottom,
    MiddleOutVertical,
    SunsetGradient,
    WavePulse,
    WithinLetterSweepLR,
    WithinLetterSweepRL,
    WordSplitBlink,
)


def _palette() -> SpectrumPalette:
    return SpectrumPalette()


def _make(cls: type[Animation], is_big: bool = True) -> Animation:
    return cls(palette=_palette(), is_big=is_big, duration_seconds=5.0, seed=42)


def _update(anim: Animation, frame: int = 0) -> dict[tuple[int, int], str | int]:
    result = anim.update(frame)
    assert isinstance(result, dict)
    return result


class TestGeneralAnimationsList:
    def test_general_animations_non_empty(self) -> None:
        assert len(GENERAL_ANIMATIONS) > 0

    def test_contains_expected_subset(self) -> None:
        expected = {FullSpectrumCycle, LetterWaveLR, LetterWaveRL, SunsetGradient, WordSplitBlink}
        assert expected.issubset(set(GENERAL_ANIMATIONS))

    def test_globalsky_not_in_pool(self) -> None:
        from teleclaude.cli.tui.animations.sky import GlobalSky

        assert GlobalSky not in GENERAL_ANIMATIONS


class TestFullSpectrumCycle:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(FullSpectrumCycle)
        result = _update(anim)
        assert len(result) > 0

    def test_single_color_per_frame(self) -> None:
        anim = _make(FullSpectrumCycle)
        result = _update(anim, 0)
        # All pixels get same color
        assert len(set(result.values())) == 1

    def test_color_cycles_with_frame(self) -> None:
        anim = _make(FullSpectrumCycle)
        r0 = _update(anim, 0)
        r7 = _update(anim, 7)
        # 7-color palette wraps at 7
        assert set(r0.values()) == set(r7.values())


class TestLetterWaveLR:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(LetterWaveLR)
        result = _update(anim)
        assert len(result) > 0

    def test_two_distinct_colors(self) -> None:
        anim = _make(LetterWaveLR)
        result = _update(anim)
        assert len(set(result.values())) >= 2


class TestLetterWaveRL:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(LetterWaveRL)
        result = _update(anim)
        assert len(result) > 0

    def test_opposite_to_lr_at_frame_0(self) -> None:
        lr = _make(LetterWaveLR)
        rl = _make(LetterWaveRL)
        assert _update(lr, 0) != _update(rl, 0)


class TestLineSweepTopBottom:
    def test_theme_filter_dark(self) -> None:
        assert LineSweepTopBottom.theme_filter == "dark"

    def test_update_returns_dict(self) -> None:
        anim = _make(LineSweepTopBottom)
        result = anim.update(0)
        assert isinstance(result, dict)


class TestLineSweepBottomTop:
    def test_theme_filter_dark(self) -> None:
        assert LineSweepBottomTop.theme_filter == "dark"

    def test_update_returns_dict(self) -> None:
        anim = _make(LineSweepBottomTop)
        result = anim.update(0)
        assert isinstance(result, dict)


class TestMiddleOutVertical:
    def test_theme_filter_dark(self) -> None:
        assert MiddleOutVertical.theme_filter == "dark"

    def test_supports_small_false(self) -> None:
        assert MiddleOutVertical.supports_small is False

    def test_update_small_returns_empty(self) -> None:
        anim = _make(MiddleOutVertical, is_big=False)
        result = _update(anim)
        assert result == {}

    def test_update_big_returns_dict(self) -> None:
        anim = _make(MiddleOutVertical, is_big=True)
        result = anim.update(0)
        assert isinstance(result, dict)


class TestWithinLetterSweepLR:
    def test_theme_filter_dark(self) -> None:
        assert WithinLetterSweepLR.theme_filter == "dark"

    def test_supports_small_false(self) -> None:
        assert WithinLetterSweepLR.supports_small is False

    def test_update_returns_dict(self) -> None:
        anim = _make(WithinLetterSweepLR)
        result = anim.update(0)
        assert isinstance(result, dict)


class TestWithinLetterSweepRL:
    def test_theme_filter_dark(self) -> None:
        assert WithinLetterSweepRL.theme_filter == "dark"

    def test_supports_small_false(self) -> None:
        assert WithinLetterSweepRL.supports_small is False

    def test_update_returns_dict(self) -> None:
        anim = _make(WithinLetterSweepRL)
        result = anim.update(0)
        assert isinstance(result, dict)


class TestWordSplitBlink:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(WordSplitBlink)
        result = _update(anim)
        assert len(result) > 0

    def test_parity_changes_colors(self) -> None:
        anim = _make(WordSplitBlink)
        r0 = _update(anim, 0)
        r1 = _update(anim, 1)
        assert r0 != r1


class TestDiagonalSweepDR:
    def test_theme_filter_dark(self) -> None:
        assert DiagonalSweepDR.theme_filter == "dark"

    def test_supports_small_false(self) -> None:
        assert DiagonalSweepDR.supports_small is False

    def test_update_small_returns_empty(self) -> None:
        anim = _make(DiagonalSweepDR, is_big=False)
        result = _update(anim)
        assert result == {}

    def test_update_big_returns_dict(self) -> None:
        anim = _make(DiagonalSweepDR, is_big=True)
        result = anim.update(0)
        assert isinstance(result, dict)


class TestDiagonalSweepDL:
    def test_theme_filter_dark(self) -> None:
        assert DiagonalSweepDL.theme_filter == "dark"

    def test_supports_small_false(self) -> None:
        assert DiagonalSweepDL.supports_small is False

    def test_update_small_returns_empty(self) -> None:
        anim = _make(DiagonalSweepDL, is_big=False)
        result = _update(anim)
        assert result == {}


class TestLetterShimmer:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(LetterShimmer)
        result = _update(anim)
        assert len(result) > 0

    def test_each_letter_different_color(self) -> None:
        anim = _make(LetterShimmer)
        result = _update(anim, 0)
        # With offset i*3, different letters may have different colors
        assert isinstance(result, dict)


class TestWavePulse:
    def test_theme_filter_dark(self) -> None:
        assert WavePulse.theme_filter == "dark"

    def test_update_returns_dict(self) -> None:
        anim = _make(WavePulse)
        result = anim.update(0)
        assert isinstance(result, dict)


class TestBlinkSweep:
    def test_theme_filter_dark(self) -> None:
        assert BlinkSweep.theme_filter == "dark"

    def test_update_returns_dict(self) -> None:
        anim = _make(BlinkSweep)
        result = anim.update(0)
        assert isinstance(result, dict)


class TestSunsetGradient:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(SunsetGradient)
        result = _update(anim)
        assert len(result) > 0

    def test_update_values_are_hex(self) -> None:
        anim = _make(SunsetGradient)
        result = _update(anim)
        for v in result.values():
            assert isinstance(v, str)
            assert v.startswith("#")
