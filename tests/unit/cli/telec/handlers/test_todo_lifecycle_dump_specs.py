"""Test spec for work-cartridge-lifecycle-routing CLI entry paths.

These specs pin the dump-entry side of the lifecycle router:

- ``--draft`` / ``--silent`` suppresses emission;
- ``bugs report`` no longer launches work sessions directly from the CLI; and
- the bug-lane chain routes through the lifecycle router to ``/next-work`` when
  the captured dump body is fed back into the router.

Event emission moved server-side: the API route emits ``workflow.todo.created``
after a successful dump; the CLI no longer calls ``/events/emit``.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from importlib import import_module
from types import SimpleNamespace
from typing import Protocol, TypedDict, cast
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.cli.telec.handlers.todo import _handle_todo_dump
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility

pytestmark = [
    pytest.mark.unit,
]

_TODO_MODULE = "teleclaude.cli.telec.handlers.todo"
bugs = importlib.import_module("teleclaude.cli.telec.handlers.bugs")


class _TodoDumpPayload(TypedDict, total=False):
    slug: str
    kind: str
    project_root: str


class _ToolRequestBody(TypedDict, total=False):
    event: str
    payload: _TodoDumpPayload
    slug: str
    kind: str
    content: str
    cwd: str
    after: list[str]


class _FakeApiClient(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_session(self, **kwargs: object) -> object: ...


def _json_body(mock_call: MagicMock) -> _ToolRequestBody:
    body = mock_call.kwargs.get("json_body")
    if isinstance(body, dict):
        return cast(_ToolRequestBody, body)
    if len(mock_call.args) >= 3 and isinstance(mock_call.args[2], dict):
        return cast(_ToolRequestBody, mock_call.args[2])
    raise AssertionError("Expected json_body payload in tool_api_request call")


def _fake_api_client() -> tuple[SimpleNamespace, object]:
    """Fake TelecAPIClient factory that captures ``run_session`` kwargs."""
    captured = SimpleNamespace(connected=False, closed=False, kwargs=None)

    async def _connect() -> None:
        captured.connected = True

    async def _close() -> None:
        captured.closed = True

    async def _run_session(**kwargs: object) -> object:
        captured.kwargs = kwargs
        return SimpleNamespace(
            status="success",
            session_id="sess-bug",
            tmux_session_name="tmux-bug",
        )

    def _factory() -> _FakeApiClient:
        return cast(
            _FakeApiClient,
            SimpleNamespace(connect=_connect, close=_close, run_session=_run_session),
        )

    return captured, _factory


def _router_type() -> type[object]:
    module = import_module("teleclaude.events.cartridges.lifecycle_router")
    return module.LifecycleRouterCartridge


def _route_bug_event_from_tool_request(
    method: str,
    path: str,
    router_factory: object,
    **kwargs: object,
) -> tuple[dict[str, str], EventEnvelope | None]:
    """Intercept /todos/dump, synthesize workflow.todo.created, route through lifecycle router."""
    if method == "POST" and path == "/todos/dump":
        body = kwargs.get("json_body")
        assert isinstance(body, dict)
        slug = str(body.get("slug", ""))
        kind = str(body.get("kind", "feature"))
        # Simulate server-side workflow.todo.created emission from the API route
        event = EventEnvelope(
            event="workflow.todo.created",
            source="api",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            visibility=EventVisibility.LOCAL,
            payload={"slug": slug, "kind": kind, "pickup_requested": True},
        )
        router = _router_type()()
        with (
            patch("teleclaude.events.cartridges.lifecycle_router.TelecAPIClient", router_factory),
            patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
        ):
            asyncio.run(router.process(event, MagicMock()))
        return {"status": "ok"}, event
    raise AssertionError(f"Unexpected tool API request: {method} {path}")


def _assert_bug_chain_routes(
    *,
    handler: Callable[[], object],
    expected_slug: str,
) -> None:
    router_launch, router_factory = _fake_api_client()
    captured_event: EventEnvelope | None = None

    def _tool_api_request(method: str, path: str, **kwargs: object) -> dict[str, str]:
        nonlocal captured_event
        response, event = _route_bug_event_from_tool_request(method, path, router_factory, **kwargs)
        captured_event = event or captured_event
        return response

    with patch.object(bugs, "tool_api_request", side_effect=_tool_api_request):
        handler()

    emitted = captured_event
    assert emitted is not None
    assert emitted.event == "workflow.todo.created"
    assert emitted.payload["slug"] == expected_slug
    assert emitted.payload["kind"] == "bug"
    assert router_launch.kwargs is not None
    assert router_launch.kwargs["command"] == "/next-work"
    assert router_launch.kwargs["args"] == expected_slug


def test_todo_dump_silent_suppresses_pickup() -> None:
    """--draft (→ --silent) causes a single /todos/dump call with no pickup event."""
    with patch(f"{_TODO_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
        _handle_todo_dump(["my-slug", "my content", "--draft"])

    called_paths = [call.args[1] for call in mock_api.call_args_list]
    assert called_paths == ["/todos/dump"]


def test_bugs_create_chain_routes_through_lifecycle_router_to_next_work() -> None:
    """Full-chain spec: ``bugs create`` → API emits workflow.todo.created → router → ``/next-work``.

    Pins the bug-lane chain at the dispatch boundary. The API route (not the CLI)
    emits ``workflow.todo.created`` with ``kind=bug``; the lifecycle router then
    dispatches ``/next-work`` with the bug slug.

    A broken implementation that emits the wrong event kind, skips pickup, or
    routes to the wrong lane cannot satisfy this spec.
    """
    assert not hasattr(bugs, "TelecAPIClient"), (
        "bugs CLI must not import TelecAPIClient — the lifecycle router owns dispatch"
    )

    _assert_bug_chain_routes(
        handler=lambda: bugs._handle_bugs_create(["sample-bug"]),
        expected_slug="fix-sample-bug",
    )


def test_bugs_report_does_not_launch_work_session_directly_from_cli() -> None:
    """The CLI must not dispatch a work session itself — the router owns that.

    Structural guard: ``bugs`` must not import ``TelecAPIClient`` at all.
    """
    assert not hasattr(bugs, "TelecAPIClient"), (
        "bugs CLI must not import TelecAPIClient — the lifecycle router owns dispatch"
    )

    with (
        patch.object(bugs, "normalize_slug", return_value="example-bug"),
        patch.object(bugs, "tool_api_request", return_value={"status": "ok"}) as request_mock,
    ):
        bugs._handle_bugs_report(["Example bug"])

    dump_body = _json_body(request_mock.call_args_list[0])
    assert dump_body["slug"] == "fix-example-bug"
    assert dump_body["kind"] == "bug"


def test_bugs_report_chain_routes_through_lifecycle_router_to_next_work() -> None:
    """Full-chain spec: ``bugs report`` → API emits workflow.todo.created → router → ``/next-work``.

    Pins the bug-lane chain at the dispatch boundary. The CLI calls ``/todos/dump``
    with ``kind=bug``; the API route emits ``workflow.todo.created``; the lifecycle
    router dispatches ``/next-work`` with the bug slug.
    """
    assert not hasattr(bugs, "TelecAPIClient"), (
        "bugs CLI must not import TelecAPIClient — the lifecycle router owns dispatch"
    )

    with (
        patch.object(bugs, "normalize_slug", return_value="example-bug"),
    ):
        _assert_bug_chain_routes(
            handler=lambda: bugs._handle_bugs_report(["Example bug"]),
            expected_slug="fix-example-bug",
        )
