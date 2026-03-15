"""Characterization tests for teleclaude.cli.tui.widgets.telec_footer."""

from __future__ import annotations

import pytest

from teleclaude.api_models import AgentAvailabilityDTO
from teleclaude.cli.tui.widgets.telec_footer import FooterActionButton, TelecFooter


def _make_info(*, available: bool = True) -> AgentAvailabilityDTO:
    return AgentAvailabilityDTO(agent="claude", available=available, status="available")


# --- TelecFooter._build_pane_theming_cells ---


@pytest.mark.unit
def test_build_pane_theming_cells_returns_four_cells() -> None:
    footer = TelecFooter()
    cells = footer._build_pane_theming_cells()
    assert len(cells) == 4


@pytest.mark.unit
def test_build_pane_theming_cells_all_outline_when_off() -> None:
    footer = TelecFooter()
    footer.pane_theming_mode = "off"
    cells = footer._build_pane_theming_cells()
    assert all(ch == "\u25fb" for ch, _ in cells)


@pytest.mark.unit
def test_build_pane_theming_cells_fills_correct_count_for_agent_plus() -> None:
    footer = TelecFooter()
    footer.pane_theming_mode = "agent_plus"
    cells = footer._build_pane_theming_cells()
    assert sum(1 for ch, _ in cells if ch == "\u25fc") == 4


# --- TelecFooter.get_persisted_state ---


@pytest.mark.unit
def test_get_persisted_state_includes_required_keys() -> None:
    footer = TelecFooter()
    state = footer.get_persisted_state()
    assert "animation_mode" in state
    assert "pane_theming_mode" in state


@pytest.mark.unit
def test_get_persisted_state_reflects_current_values() -> None:
    footer = TelecFooter()
    footer.animation_mode = "periodic"
    footer.pane_theming_mode = "highlight"
    state = footer.get_persisted_state()
    assert state["animation_mode"] == "periodic"
    assert state["pane_theming_mode"] == "highlight"


# --- TelecFooter.load_persisted_state ---


@pytest.mark.unit
def test_load_persisted_state_restores_animation_mode() -> None:
    footer = TelecFooter()
    footer.load_persisted_state({"animation_mode": "party"})
    assert footer.animation_mode == "party"


@pytest.mark.unit
def test_load_persisted_state_ignores_invalid_animation_mode() -> None:
    footer = TelecFooter()
    footer.animation_mode = "off"
    footer.load_persisted_state({"animation_mode": "bogus"})
    assert footer.animation_mode == "off"


# --- TelecFooter._build_agent_pill ---


@pytest.mark.unit
def test_build_agent_pill_available_text_contains_checkmark() -> None:
    footer = TelecFooter(agent_availability={"claude": _make_info(available=True)})
    pill = footer._build_agent_pill("claude")
    assert "\u2714" in pill.plain  # ✔


@pytest.mark.unit
def test_build_agent_pill_unavailable_text_contains_cross() -> None:
    footer = TelecFooter(agent_availability={"claude": _make_info(available=False)})
    pill = footer._build_agent_pill("claude")
    assert "\u2718" in pill.plain  # ✘


@pytest.mark.unit
def test_build_agent_pill_no_availability_info_shows_cross() -> None:
    footer = TelecFooter()  # empty agent_availability
    pill = footer._build_agent_pill("claude")
    assert "\u2718" in pill.plain  # ✘ when no info present


# --- FooterActionButton ---


@pytest.mark.unit
def test_footer_action_button_is_importable() -> None:
    assert FooterActionButton is not None
