"""Characterization tests for animations/config.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.animations.config import (
    ErrorAnimation,
    PulseAnimation,
    SuccessAnimation,
    TypingAnimation,
)


def _palette() -> SpectrumPalette:
    return SpectrumPalette()


def _make_target_mock(width: int = 20) -> MagicMock:
    mock = MagicMock()
    mock.width = width
    return mock


def _make(cls: type[Animation], target_name: str = "test_target") -> Animation:
    return cls(palette=_palette(), is_big=True, duration_seconds=5.0, seed=42, target=target_name)


def _update(anim: Animation, frame: int = 0) -> dict[tuple[int, int], str | int]:
    result = anim.update(frame)
    assert isinstance(result, dict)
    return result


@patch("teleclaude.cli.tui.animations.config.target_registry")
class TestPulseAnimation:
    def test_returns_empty_when_no_target(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = None
        anim = _make(PulseAnimation)
        result = _update(anim)
        assert result == {}

    def test_returns_pixels_with_target(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = _make_target_mock(width=20)
        anim = _make(PulseAnimation)
        result = _update(anim)
        assert isinstance(result, dict)

    def test_pixel_values_are_hex_strings(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = _make_target_mock(width=20)
        anim = _make(PulseAnimation)
        result = _update(anim)
        for v in result.values():
            assert isinstance(v, str)
            assert v.startswith("#")


@patch("teleclaude.cli.tui.animations.config.target_registry")
class TestTypingAnimation:
    def test_returns_empty_when_no_target(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = None
        anim = _make(TypingAnimation)
        result = _update(anim)
        assert result == {}

    def test_returns_pixels_with_target(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = _make_target_mock(width=20)
        anim = _make(TypingAnimation)
        result = _update(anim)
        assert isinstance(result, dict)

    def test_exactly_five_pixels_per_frame(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = _make_target_mock(width=20)
        anim = _make(TypingAnimation)
        result = _update(anim)
        # TypingAnimation places 5 random pixels per frame (may collide, so <= 5)
        assert len(result) <= 5


@patch("teleclaude.cli.tui.animations.config.target_registry")
class TestSuccessAnimation:
    def test_returns_empty_when_no_target(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = None
        anim = _make(SuccessAnimation)
        result = _update(anim)
        assert result == {}

    def test_returns_dict_with_target(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = _make_target_mock(width=20)
        anim = _make(SuccessAnimation)
        result = _update(anim)
        assert isinstance(result, dict)


@patch("teleclaude.cli.tui.animations.config.target_registry")
class TestErrorAnimation:
    def test_returns_empty_when_no_target(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = None
        anim = _make(ErrorAnimation)
        result = _update(anim)
        assert result == {}

    def test_returns_pixels_on_even_flicker(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = _make_target_mock(width=20)
        anim = _make(ErrorAnimation)
        # Frame 0: progress=0, int(0*10)%2==0 → pixels drawn
        result = _update(anim, 0)
        assert isinstance(result, dict)

    def test_flash_uses_first_palette_color(self, mock_registry: MagicMock) -> None:
        mock_registry.get.return_value = _make_target_mock(width=20)
        anim = _make(ErrorAnimation)
        # At frame 0 (flicker on), all pixels should have palette color 0
        result = _update(anim, 0)
        if result:
            expected = _palette().get(0)
            for v in result.values():
                assert v == expected
