"""Unit tests for canonical runtime agent routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.core import agent_routing


def _mock_enabled_config(*agents: str) -> SimpleNamespace:
    return SimpleNamespace(agents={name: SimpleNamespace(enabled=True) for name in agents})


@pytest.mark.asyncio
async def test_resolve_routable_agent_rejects_explicit_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_routing, "config", _mock_enabled_config("claude"))
    monkeypatch.setattr(agent_routing, "normalize_agent_name", lambda value: value.strip().lower())
    monkeypatch.setattr(agent_routing, "get_enabled_agents", lambda: ("claude",))
    monkeypatch.setattr(
        agent_routing.db,
        "get_agent_availability",
        AsyncMock(return_value={"status": "unavailable"}),
    )

    with pytest.raises(agent_routing.AgentRoutingError) as exc_info:
        await agent_routing.resolve_routable_agent("claude", source="test.explicit")

    assert exc_info.value.code == "unavailable"


@pytest.mark.asyncio
async def test_resolve_routable_agent_rejects_explicit_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_routing, "config", _mock_enabled_config("claude"))
    monkeypatch.setattr(agent_routing, "normalize_agent_name", lambda value: value.strip().lower())
    monkeypatch.setattr(agent_routing, "get_enabled_agents", lambda: ("claude",))
    monkeypatch.setattr(
        agent_routing.db,
        "get_agent_availability",
        AsyncMock(return_value={"status": "degraded"}),
    )

    with pytest.raises(agent_routing.AgentRoutingError) as exc_info:
        await agent_routing.resolve_routable_agent("claude", source="test.explicit")

    assert exc_info.value.code == "degraded"


@pytest.mark.asyncio
async def test_resolve_routable_agent_implicit_skips_unavailable_and_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routing, "config", _mock_enabled_config("claude", "gemini", "codex"))
    monkeypatch.setattr(agent_routing, "get_enabled_agents", lambda: ("claude", "gemini", "codex"))

    async def _availability(agent_name: str) -> dict[str, str]:
        if agent_name == "claude":
            return {"status": "degraded"}
        if agent_name == "gemini":
            return {"status": "unavailable"}
        return {"status": "available"}

    monkeypatch.setattr(agent_routing.db, "get_agent_availability", AsyncMock(side_effect=_availability))

    routed = await agent_routing.resolve_routable_agent(None, source="test.implicit")
    assert routed == "codex"


@pytest.mark.asyncio
async def test_resolve_routable_agent_implicit_rejects_when_no_routable_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routing, "config", _mock_enabled_config("claude", "gemini"))
    monkeypatch.setattr(agent_routing, "get_enabled_agents", lambda: ("claude", "gemini"))
    monkeypatch.setattr(
        agent_routing.db,
        "get_agent_availability",
        AsyncMock(side_effect=[{"status": "degraded"}, {"status": "unavailable"}]),
    )

    with pytest.raises(agent_routing.AgentRoutingError) as exc_info:
        await agent_routing.resolve_routable_agent(None, source="test.implicit")

    assert exc_info.value.code == "no_routable_agent"


@pytest.mark.asyncio
async def test_resolve_routable_agent_rejects_disabled_explicit_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_routing,
        "config",
        SimpleNamespace(agents={"codex": SimpleNamespace(enabled=False), "claude": SimpleNamespace(enabled=True)}),
    )
    monkeypatch.setattr(agent_routing, "get_enabled_agents", lambda: ("claude",))
    monkeypatch.setattr(agent_routing, "normalize_agent_name", lambda value: value.strip().lower())
    monkeypatch.setattr(
        agent_routing.db,
        "get_agent_availability",
        AsyncMock(return_value={"status": "available"}),
    )

    with pytest.raises(agent_routing.AgentRoutingError) as exc_info:
        await agent_routing.resolve_routable_agent("codex", source="test.disabled")

    assert exc_info.value.code == "disabled"
