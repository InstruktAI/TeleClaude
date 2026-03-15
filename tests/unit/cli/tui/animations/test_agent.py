"""Characterization tests for animations/agent.py."""

from __future__ import annotations

from teleclaude.cli.tui.animation_colors import AgentPalette
from teleclaude.cli.tui.animations.agent import (
    AGENT_ANIMATIONS,
    AgentBreathing,
    AgentFadeCycle,
    AgentHeartbeat,
    AgentLineSweep,
    AgentMiddleOut,
    AgentPulse,
    AgentSparkle,
    AgentWaveLR,
    AgentWaveRL,
    AgentWordSplit,
)
from teleclaude.cli.tui.animations.base import Animation


def _palette() -> AgentPalette:
    return AgentPalette("claude")


def _make(cls: type[Animation], is_big: bool = True) -> Animation:
    return cls(palette=_palette(), is_big=is_big, duration_seconds=5.0, seed=42)


def _update(anim: Animation, frame: int = 0) -> dict[tuple[int, int], str | int]:
    result = anim.update(frame)
    assert isinstance(result, dict)
    return result


class TestAgentAnimationsList:
    def test_agent_animations_contains_expected_classes(self) -> None:
        expected = {
            AgentPulse,
            AgentWaveLR,
            AgentWaveRL,
            AgentLineSweep,
            AgentMiddleOut,
            AgentHeartbeat,
            AgentWordSplit,
            AgentFadeCycle,
            AgentBreathing,
        }
        assert set(AGENT_ANIMATIONS) == expected


class TestAgentPulse:
    def test_update_returns_dict(self) -> None:
        anim = _make(AgentPulse)
        result = _update(anim)
        assert len(result) > 0

    def test_update_values_are_hex_strings(self) -> None:
        anim = _make(AgentPulse)
        result = _update(anim)
        for v in result.values():
            assert isinstance(v, str)
            assert v.startswith("#")

    def test_color_cycles_at_palette_length(self) -> None:
        anim = _make(AgentPulse)
        # Palette has 3 colors; frame 0 and 3 should match
        r0 = _update(anim, 0)
        r3 = _update(anim, 3)
        assert set(r0.values()) == set(r3.values())


class TestAgentWaveLR:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(AgentWaveLR)
        result = _update(anim)
        assert len(result) > 0

    def test_active_letter_differs_from_rest(self) -> None:
        anim = _make(AgentWaveLR)
        result = _update(anim)
        colors = set(result.values())
        # At least 2 different colors (hi vs dim)
        assert len(colors) >= 2


class TestAgentWaveRL:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(AgentWaveRL)
        result = _update(anim)
        assert len(result) > 0

    def test_direction_opposite_to_lr(self) -> None:
        lr = _make(AgentWaveLR, is_big=True)
        rl = _make(AgentWaveRL, is_big=True)
        lr_result = _update(lr, 0)
        rl_result = _update(rl, 0)
        # Same pixels but which letter is active differs
        assert lr_result != rl_result


class TestAgentLineSweep:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(AgentLineSweep)
        result = _update(anim)
        assert len(result) > 0

    def test_rows_produce_two_distinct_colors(self) -> None:
        anim = _make(AgentLineSweep)
        result = _update(anim)
        colors = set(result.values())
        assert len(colors) >= 2


class TestAgentMiddleOut:
    def test_supports_small_false(self) -> None:
        assert AgentMiddleOut.supports_small is False

    def test_update_big_returns_pixels(self) -> None:
        anim = _make(AgentMiddleOut, is_big=True)
        result = _update(anim)
        assert len(result) > 0

    def test_update_small_returns_empty(self) -> None:
        anim = _make(AgentMiddleOut, is_big=False)
        result = _update(anim)
        assert result == {}


class TestAgentSparkle:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(AgentSparkle)
        result = _update(anim)
        assert len(result) > 0

    def test_non_sparkle_pixels_are_minus_one(self) -> None:
        anim = _make(AgentSparkle)
        result = _update(anim)
        # Most pixels should be -1 (dimmed)
        minus_ones = sum(1 for v in result.values() if v == -1)
        assert minus_ones > 0


class TestAgentHeartbeat:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(AgentHeartbeat)
        result = _update(anim)
        assert len(result) > 0

    def test_frame_cycle_repeats_at_6(self) -> None:
        anim = _make(AgentHeartbeat)
        r0 = _update(anim, 0)
        r6 = _update(anim, 6)
        assert set(r0.values()) == set(r6.values())


class TestAgentWordSplit:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(AgentWordSplit)
        result = _update(anim)
        assert len(result) > 0

    def test_parity_flips_colors(self) -> None:
        anim = _make(AgentWordSplit)
        r0 = _update(anim, 0)
        r1 = _update(anim, 1)
        assert r0 != r1


class TestAgentFadeCycle:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(AgentFadeCycle)
        result = _update(anim)
        assert len(result) > 0

    def test_sequence_repeats_at_4(self) -> None:
        anim = _make(AgentFadeCycle)
        r0 = _update(anim, 0)
        r4 = _update(anim, 4)
        assert set(r0.values()) == set(r4.values())


class TestAgentBreathing:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(AgentBreathing)
        result = _update(anim)
        assert len(result) > 0

    def test_sequence_repeats_at_8(self) -> None:
        anim = _make(AgentBreathing)
        r0 = _update(anim, 0)
        r8 = _update(anim, 8)
        assert set(r0.values()) == set(r8.values())
