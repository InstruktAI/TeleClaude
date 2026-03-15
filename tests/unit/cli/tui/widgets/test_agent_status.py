"""Characterization tests for teleclaude.cli.tui.widgets.agent_status."""

from __future__ import annotations

import pytest

from teleclaude.api_models import AgentAvailabilityDTO
from teleclaude.cli.tui.widgets.agent_status import (
    build_agent_render_spec,
    is_agent_degraded,
    is_agent_selectable,
)


def _make_info(
    *,
    available: bool | None = True,
    status: str | None = "available",
    reason: str | None = None,
) -> AgentAvailabilityDTO:
    return AgentAvailabilityDTO(agent="claude", available=available, status=status, reason=reason)


# --- is_agent_degraded ---


@pytest.mark.unit
def test_is_agent_degraded_returns_false_when_info_is_none() -> None:
    assert is_agent_degraded(None) is False


@pytest.mark.unit
def test_is_agent_degraded_returns_true_when_status_is_degraded() -> None:
    info = _make_info(available=True, status="degraded")
    assert is_agent_degraded(info) is True


@pytest.mark.unit
def test_is_agent_degraded_returns_true_when_reason_starts_with_degraded() -> None:
    info = _make_info(available=True, status="available", reason="degraded: rate-limited")
    assert is_agent_degraded(info) is True


@pytest.mark.unit
def test_is_agent_degraded_returns_false_when_available() -> None:
    info = _make_info(available=True, status="available")
    assert is_agent_degraded(info) is False


# --- is_agent_selectable ---


@pytest.mark.unit
def test_is_agent_selectable_returns_false_when_info_is_none() -> None:
    assert is_agent_selectable(None) is False


@pytest.mark.unit
def test_is_agent_selectable_returns_true_when_available() -> None:
    info = _make_info(available=True)
    assert is_agent_selectable(info) is True


@pytest.mark.unit
def test_is_agent_selectable_returns_false_when_not_available() -> None:
    info = _make_info(available=False)
    assert is_agent_selectable(info) is False


# --- build_agent_render_spec ---


@pytest.mark.unit
def test_build_agent_render_spec_returns_available_status() -> None:
    info = _make_info(available=True, status="available")
    spec = build_agent_render_spec("claude", info)
    assert spec.status == "available"
    assert spec.bold is True
    assert spec.selectable is True


@pytest.mark.unit
def test_build_agent_render_spec_returns_degraded_status() -> None:
    info = _make_info(available=True, status="degraded")
    spec = build_agent_render_spec("claude", info)
    assert spec.status == "degraded"
    assert spec.bold is False


@pytest.mark.unit
def test_build_agent_render_spec_returns_unavailable_status() -> None:
    info = _make_info(available=False, status="unavailable")
    spec = build_agent_render_spec("claude", info)
    assert spec.status == "unavailable"
    assert spec.bold is False
    assert spec.selectable is False


@pytest.mark.unit
def test_build_agent_render_spec_records_agent_name() -> None:
    spec = build_agent_render_spec("gemini", None)
    assert spec.agent == "gemini"


@pytest.mark.unit
def test_build_agent_render_spec_unavailable_detail_suffix_shown_by_default() -> None:
    info = _make_info(available=False, status="unavailable")
    spec = build_agent_render_spec("codex", info, unavailable_detail="offline")
    assert "(offline)" in spec.text


@pytest.mark.unit
def test_build_agent_render_spec_unavailable_detail_hidden_when_flag_false() -> None:
    info = _make_info(available=False, status="unavailable")
    spec = build_agent_render_spec("codex", info, unavailable_detail="offline", show_unavailable_detail=False)
    assert "(offline)" not in spec.text
