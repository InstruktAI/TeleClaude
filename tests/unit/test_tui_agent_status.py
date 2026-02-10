"""Unit tests for shared TUI agent status renderer."""

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.widgets.agent_status import (
    build_agent_render_spec,
    is_agent_degraded,
    is_agent_selectable,
)


def test_available_agent_spec_is_bold_and_selectable() -> None:
    info = AgentAvailabilityInfo(
        agent="claude",
        available=True,
        status="available",
        unavailable_until=None,
        reason=None,
    )

    spec = build_agent_render_spec("claude", info)

    assert spec.status == "available"
    assert spec.selectable is True
    assert spec.bold is True
    assert "✔" in spec.text


def test_degraded_agent_spec_is_selectable_not_bold() -> None:
    info = AgentAvailabilityInfo(
        agent="codex",
        available=True,
        status="degraded",
        unavailable_until=None,
        reason="degraded_api",
    )

    spec = build_agent_render_spec("codex", info)

    assert is_agent_degraded(info) is True
    assert is_agent_selectable(info) is True
    assert spec.status == "degraded"
    assert spec.selectable is True
    assert spec.bold is False
    assert "~" in spec.text


def test_unavailable_agent_spec_is_muted_and_non_selectable() -> None:
    info = AgentAvailabilityInfo(
        agent="gemini",
        available=False,
        status="unavailable",
        unavailable_until="2026-02-11T00:00:00+00:00",
        reason="rate_limited",
    )

    spec = build_agent_render_spec("gemini", info, unavailable_detail="5m", show_unavailable_detail=True)

    assert spec.status == "unavailable"
    assert spec.selectable is False
    assert spec.bold is False
    assert "✘ (5m)" in spec.text
