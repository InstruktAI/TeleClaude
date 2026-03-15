"""Characterization tests for teleclaude.cli.tui.widgets.modals."""

from __future__ import annotations

import pytest

from teleclaude.api_models import AgentAvailabilityDTO
from teleclaude.cli.tui.widgets.modals import (
    ModeSelector,
    SessionIdTypeSelector,
    _is_agent_selectable,
)


def _make_info(
    *,
    available: bool | None = True,
    status: str | None = "available",
    reason: str | None = None,
) -> AgentAvailabilityDTO:
    return AgentAvailabilityDTO(agent="claude", available=available, status=status, reason=reason)


# --- _is_agent_selectable ---


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_info_none() -> None:
    """Absent info means the local cache hasn't loaded yet — selectable by default."""
    assert _is_agent_selectable(None) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_available() -> None:
    info = _make_info(available=True)
    assert _is_agent_selectable(info) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_degraded_status() -> None:
    info = _make_info(available=False, status="degraded")
    assert _is_agent_selectable(info) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_reason_starts_with_degraded() -> None:
    info = _make_info(available=False, status="unavailable", reason="degraded: cold")
    assert _is_agent_selectable(info) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_false_when_unavailable_no_degraded() -> None:
    info = _make_info(available=False, status="unavailable")
    assert _is_agent_selectable(info) is False


# --- ModeSelector ---


@pytest.mark.unit
def test_mode_selector_default_selected_is_slow_index() -> None:
    """Default selected=1 which maps to 'slow' in _MODES."""
    sel = ModeSelector()
    assert sel.selected == 1
    assert sel.selected_mode == "slow"


@pytest.mark.unit
def test_mode_selector_action_next_wraps_around() -> None:
    sel = ModeSelector()
    sel.selected = 2  # last index (len=3)
    sel.action_next()
    assert sel.selected == 0


@pytest.mark.unit
def test_mode_selector_action_prev_wraps_around() -> None:
    sel = ModeSelector()
    sel.selected = 0
    sel.action_prev()
    assert sel.selected == len(ModeSelector._MODES) - 1


# --- SessionIdTypeSelector ---


@pytest.mark.unit
def test_session_id_type_selector_is_importable() -> None:
    assert SessionIdTypeSelector is not None


@pytest.mark.unit
def test_session_id_type_selector_types_has_two_entries() -> None:
    assert len(SessionIdTypeSelector._TYPES) == 2


@pytest.mark.unit
def test_session_id_type_selector_cell_width_is_16() -> None:
    assert SessionIdTypeSelector._CELL_WIDTH == 16
