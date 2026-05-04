"""Lifecycle-router contract tests for todo dump handling and DOR assessment.

These tests pin the lifecycle-router cartridge's routing behavior: dump events
are dispatched by ``payload.kind`` (pure function of the payload), while
non-dump planning triggers continue to drive DOR assessment.
"""

from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility

pytestmark = [
    pytest.mark.unit,
]

_NON_DUMP_TRIGGER_EVENTS: tuple[str, ...] = (
    "domain.software-development.planning.artifact_changed",
    "domain.software-development.planning.todo_created",
    "domain.software-development.planning.todo_activated",
    "domain.software-development.planning.dependency_resolved",
)


def _make_event(
    *,
    slug: str = "my-slug",
    kind: str | None = None,
    event_type: str = "domain.software-development.planning.todo_dumped",
) -> EventEnvelope:
    payload: dict[str, str] = {"slug": slug, "project_root": "/project"}
    if kind is not None:
        payload["kind"] = kind
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        payload=payload,
    )


def _router_type() -> type[object]:
    module = import_module("teleclaude.events.cartridges.lifecycle_router")
    return module.LifecycleRouterCartridge


def _fake_api_client() -> tuple[SimpleNamespace, object]:
    captured = SimpleNamespace(
        connected=False,
        closed=False,
        kwargs=None,
    )

    async def _connect() -> None:
        captured.connected = True

    async def _close() -> None:
        captured.closed = True

    async def _run_session(**kwargs: object) -> dict[str, str]:
        captured.kwargs = kwargs
        return {"session_id": "sess-router", "tmux_session_name": "tmux-router"}

    def _factory() -> SimpleNamespace:
        return SimpleNamespace(connect=_connect, close=_close, run_session=_run_session)

    return captured, _factory


def test_lifecycle_router_export_surface_replaces_prepare_cartridge_name() -> None:
    router_type = _router_type()
    cartridge_module = import_module("teleclaude.events.cartridges")
    exports = cartridge_module.__all__

    assert router_type.__name__ == "LifecycleRouterCartridge"
    assert "LifecycleRouterCartridge" in exports
    assert "PrepareCartridge" not in exports


def test_lifecycle_router_describes_lifecycle_router_identity() -> None:
    router = _router_type()()

    assert router.describe() == "lifecycle-router"


def test_daemon_pipeline_registers_the_lifecycle_router_cartridge() -> None:
    platform_module = import_module("teleclaude.daemon_event_platform")
    router_type = _router_type()
    mixin_type = cast(type[object], platform_module._DaemonEventPlatformMixin)

    def _stub_domain_runner(self: object) -> None:
        _ = self

    dummy_platform_type = type(
        "_DummyPlatform",
        (mixin_type,),
        {"_build_domain_runner": _stub_domain_runner},
    )

    pipeline = dummy_platform_type()._build_pipeline(MagicMock(), MagicMock())

    assert any(isinstance(cartridge, router_type) for cartridge in pipeline._cartridges)


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", _NON_DUMP_TRIGGER_EVENTS)
async def test_non_dump_planning_events_still_run_dor_assessment(event_type: str) -> None:
    """Every non-dump planning trigger still routes into DOR assessment.

    FR6 and the subscribed-trigger constraint require the same five planning
    trigger events to remain attached to the router, and the four non-dump
    triggers must still drive DOR assessment after the rename. A regression
    that drops any of ``artifact_changed``, ``todo_created``, ``todo_activated``,
    or ``dependency_resolved`` from the assessment path must fail this spec.
    """
    router = _router_type()()
    event = _make_event(event_type=event_type)
    context = MagicMock()

    with patch.object(router, "_assess", new=AsyncMock()) as assess_mock:
        result = await router.process(event, context)

    assert result is event
    assess_mock.assert_awaited_once_with("my-slug", event, context)


@pytest.mark.asyncio
async def test_default_todo_lane_routes_to_next_prepare() -> None:
    router = _router_type()()
    captured, factory = _fake_api_client()

    with (
        patch("teleclaude.cli.api_client.TelecAPIClient", factory),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        result = await router.process(_make_event(kind="todo"), MagicMock())

    assert result is not None
    assert captured.connected is True
    assert captured.closed is True
    assert captured.kwargs is not None
    assert captured.kwargs["command"] == "/next-prepare"
    assert captured.kwargs["args"] == "my-slug"


@pytest.mark.asyncio
async def test_prepped_lane_routes_to_next_work() -> None:
    router = _router_type()()
    captured, factory = _fake_api_client()

    with (
        patch("teleclaude.cli.api_client.TelecAPIClient", factory),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        result = await router.process(_make_event(kind="prepped"), MagicMock())

    assert result is not None
    assert captured.kwargs is not None
    assert captured.kwargs["command"] == "/next-work"
    assert captured.kwargs["args"] == "my-slug"


@pytest.mark.asyncio
async def test_built_lane_routes_to_detached_next_work() -> None:
    router = _router_type()()
    captured, factory = _fake_api_client()

    with (
        patch("teleclaude.cli.api_client.TelecAPIClient", factory),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        result = await router.process(_make_event(kind="built"), MagicMock())

    assert result is not None
    assert captured.kwargs is not None
    assert captured.kwargs["command"] == "/next-work"
    assert captured.kwargs["args"] == "my-slug"
    assert captured.kwargs["detach"] is True


@pytest.mark.asyncio
async def test_bug_lane_routes_to_next_work_with_bug_reasoning_profile() -> None:
    router = _router_type()()
    captured, factory = _fake_api_client()

    with (
        patch("teleclaude.cli.api_client.TelecAPIClient", factory),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        result = await router.process(_make_event(kind="bug"), MagicMock())

    assert result is not None
    assert captured.kwargs is not None
    assert captured.kwargs["command"] == "/next-work"
    assert captured.kwargs["agent"] == "claude"
    assert captured.kwargs["thinking_mode"] == "slow"


@pytest.mark.asyncio
async def test_missing_kind_degrades_to_next_prepare() -> None:
    router = _router_type()()
    captured, factory = _fake_api_client()

    with (
        patch("teleclaude.cli.api_client.TelecAPIClient", factory),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        result = await router.process(_make_event(), MagicMock())

    assert result is not None
    assert captured.kwargs is not None
    assert captured.kwargs["command"] == "/next-prepare"


@pytest.mark.asyncio
async def test_unknown_kind_degrades_to_next_prepare() -> None:
    router = _router_type()()
    captured, factory = _fake_api_client()

    with (
        patch("teleclaude.cli.api_client.TelecAPIClient", factory),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        result = await router.process(_make_event(kind="unexpected-lane"), MagicMock())

    assert result is not None
    assert captured.kwargs is not None
    assert captured.kwargs["command"] == "/next-prepare"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ["todo", "prepped", "bug", None, "unexpected-lane"],
    ids=["default-todo", "prepped", "bug", "missing-kind", "unknown-kind"],
)
async def test_dump_routing_is_a_pure_function_of_payload_kind(kind: str | None) -> None:
    """Dump routing must resolve from ``payload.kind`` without reading todo state.

    FR4 requires that the orchestration path is selected from the event payload
    alone and must not depend on rereading todo state after the event is
    emitted. This test patches the state-read boundary (``get_todos_db``, the
    single entry point into the todo-state store) and proves it is never
    touched while the router dispatches a dump event, regardless of the
    ``kind`` branch taken. An implementation that re-reads todo state during
    routing — even if it happens to pick the same command by coincidence —
    must fail this spec.
    """
    router = _router_type()()
    _, factory = _fake_api_client()
    state_read_mock = MagicMock()

    with (
        patch("teleclaude.cli.api_client.TelecAPIClient", factory),
        patch("teleclaude.core.todos_db.get_todos_db", new=state_read_mock),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        result = await router.process(_make_event(kind=kind), MagicMock())

    assert result is not None
    state_read_mock.assert_not_called()
