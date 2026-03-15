"""Characterization tests for animation_colors.py."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.animation_colors import (
    AgentPalette,
    MultiGradient,
    PaletteRegistry,
    SectionPalette,
    SpectrumPalette,
    palette_registry,
)


class TestMultiGradient:
    def test_raises_on_empty_stops(self) -> None:
        with pytest.raises(ValueError):
            MultiGradient([])

    def test_single_stop_returns_same_color(self) -> None:
        mg = MultiGradient(["#ff0000"])
        result = mg.get(0.0)
        assert result.startswith("#")
        assert len(result) == 7

    def test_single_stop_any_factor(self) -> None:
        mg = MultiGradient(["#ff0000"])
        assert mg.get(0.0) == mg.get(0.5) == mg.get(1.0)

    def test_two_stops_factor_zero_returns_first(self) -> None:
        mg = MultiGradient(["#ff0000", "#0000ff"])
        result = mg.get(0.0)
        # At factor 0, should be close to red (#ff0000)
        assert result == "#ff0000"

    def test_two_stops_factor_one_returns_second(self) -> None:
        mg = MultiGradient(["#ff0000", "#0000ff"])
        result = mg.get(1.0)
        assert result == "#0000ff"

    def test_clamps_factor_below_zero(self) -> None:
        mg = MultiGradient(["#ff0000", "#0000ff"])
        assert mg.get(-1.0) == mg.get(0.0)

    def test_clamps_factor_above_one(self) -> None:
        mg = MultiGradient(["#ff0000", "#0000ff"])
        assert mg.get(2.0) == mg.get(1.0)

    def test_returns_hex_string(self) -> None:
        mg = MultiGradient(["#ff0000", "#00ff00", "#0000ff"])
        result = mg.get(0.5)
        assert result.startswith("#")
        assert len(result) == 7


class TestSpectrumPalette:
    def test_name_is_spectrum(self) -> None:
        p = SpectrumPalette()
        assert p.name == "spectrum"

    def test_len_is_seven(self) -> None:
        p = SpectrumPalette()
        assert len(p) == 7

    def test_get_returns_hex_string(self) -> None:
        p = SpectrumPalette()
        color = p.get(0)
        assert color.startswith("#")
        assert len(color) == 7

    def test_get_wraps_around(self) -> None:
        p = SpectrumPalette()
        assert p.get(0) == p.get(7)
        assert p.get(1) == p.get(8)

    def test_index_zero_is_red(self) -> None:
        p = SpectrumPalette()
        assert p.get(0) == "#ff0000"


class TestAgentPalette:
    def test_name_contains_agent_name(self) -> None:
        p = AgentPalette("claude")
        assert "claude" in p.name

    def test_len_is_three(self) -> None:
        p = AgentPalette("claude")
        assert len(p) == 3

    def test_get_returns_hex_string(self) -> None:
        p = AgentPalette("claude")
        for i in range(3):
            color = p.get(i)
            assert color.startswith("#")
            assert len(color) == 7

    def test_get_wraps_around(self) -> None:
        p = AgentPalette("claude")
        assert p.get(0) == p.get(3)


class TestSectionPalette:
    def test_name_matches_constructor(self) -> None:
        p = SectionPalette("telegram", [4, 6])
        assert p.name == "telegram"

    def test_len_matches_color_indices(self) -> None:
        p = SectionPalette("telegram", [4, 6])
        assert len(p) == 2

    def test_get_returns_hex_string(self) -> None:
        p = SectionPalette("telegram", [4, 6])
        color = p.get(0)
        assert color.startswith("#")
        assert len(color) == 7

    def test_get_wraps_around(self) -> None:
        p = SectionPalette("telegram", [4, 6])
        assert p.get(0) == p.get(2)


class TestPaletteRegistry:
    def test_register_and_get(self) -> None:
        reg = PaletteRegistry()
        sp = SpectrumPalette()
        reg.register(sp)
        assert reg.get("spectrum") is sp

    def test_get_missing_returns_none(self) -> None:
        reg = PaletteRegistry()
        assert reg.get("nonexistent") is None

    def test_overwrite_registration(self) -> None:
        reg = PaletteRegistry()
        p1 = SpectrumPalette()
        p2 = SpectrumPalette()
        reg.register(p1)
        reg.register(p2)
        assert reg.get("spectrum") is p2


class TestGlobalPaletteRegistry:
    def test_spectrum_registered(self) -> None:
        assert palette_registry.get("spectrum") is not None

    def test_agent_palettes_registered(self) -> None:
        for agent in ("claude", "gemini", "codex"):
            assert palette_registry.get(f"agent_{agent}") is not None

    def test_section_palettes_registered(self) -> None:
        for section in (
            "telegram",
            "whatsapp",
            "discord",
            "ai_keys",
            "people",
            "notifications",
            "environment",
            "validate",
        ):
            assert palette_registry.get(section) is not None
