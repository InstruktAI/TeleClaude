"""Test spec (xfail) for work-cartridge-lifecycle-routing CLI entry paths.

These specs pin the dump-entry side of the lifecycle router:

- each supported CLI entry path emits ``todo_dumped`` with the correct ``kind``;
- ``--draft`` suppresses emission;
- ``bugs report`` no longer launches work sessions directly from the CLI; and
- the bug-lane chain routes through the lifecycle router to ``/next-work`` when
  the captured dump body is fed back into the router.

The module-level ``pytestmark`` xfail stays until the implementation satisfies
every spec.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol, TypedDict, cast
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.cli.telec.handlers.todo import _handle_todo_dump
from teleclaude.events.envelope import EventEnvelope

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
    """Fake TelecAPIClient factory that captures ``run_session`` kwargs.

    This mirrors the real async contract (connect/run_session/close) so that
    callers using ``asyncio.run(...)`` execute cleanly — we do not patch
    ``asyncio.run`` itself, which would leave unawaited coroutines and raise
    ``RuntimeWarning``.
    """
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
    if method == "POST" and path == "/todos/dump":
        return {"status": "ok"}, None
    if method == "POST" and path == "/events/emit":
        body = kwargs.get("json_body")
        assert isinstance(body, dict)
        event = EventEnvelope.model_validate(body)
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
    assert emitted.event == "domain.software-development.planning.todo_dumped"
    assert emitted.payload["slug"] == expected_slug
    assert emitted.payload["kind"] == "bug"
    assert emitted.payload["project_root"] == str(Path.cwd())
    assert router_launch.kwargs is not None
    assert router_launch.kwargs["command"] == "/next-work"
    assert router_launch.kwargs["args"] == expected_slug


def test_todo_dump_emits_default_lane_todo_dumped_event() -> None:
    with patch(f"{_TODO_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
        _handle_todo_dump(["my-slug", "my content"])

    assert mock_api.call_count == 2
    emit_body = _json_body(mock_api.call_args_list[1])
    payload = emit_body["payload"]
    assert isinstance(payload, dict)
    assert emit_body["event"] == "domain.software-development.planning.todo_dumped"
    assert payload["slug"] == "my-slug"
    assert payload["kind"] == "todo"
    assert payload["project_root"] == str(Path.cwd())


def test_todo_dump_prepped_emits_prepped_lane_todo_dumped_event() -> None:
    with patch(f"{_TODO_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
        _handle_todo_dump(["--prepped", "my-slug", "my content"])

    assert mock_api.call_count == 2
    emit_body = _json_body(mock_api.call_args_list[1])
    payload = emit_body["payload"]
    assert isinstance(payload, dict)
    assert emit_body["event"] == "domain.software-development.planning.todo_dumped"
    assert payload["slug"] == "my-slug"
    assert payload["kind"] == "prepped"
    assert payload["project_root"] == str(Path.cwd())


def test_todo_dump_draft_suppresses_todo_dumped_event_emission() -> None:
    with patch(f"{_TODO_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
        _handle_todo_dump(["my-slug", "my content", "--draft"])

    called_paths = [call.args[1] for call in mock_api.call_args_list]
    assert called_paths == ["/todos/dump"]


def test_bugs_create_chain_routes_through_lifecycle_router_to_next_work() -> None:
    """Full-chain spec: ``bugs create`` → ``todo_dumped(kind=bug)`` → router → ``/next-work``.

    Pins the bug-lane chain at the emission boundary. ``bugs create`` must
    emit ``todo_dumped`` with ``kind=bug``, the slug, and the project context,
    and that emitted envelope is what the lifecycle router handles. A fake
    API client captures the router's launch so the test can assert that the
    router — not the CLI — launches ``/next-work`` with the bug slug.

    A broken implementation that only writes ``/todos/dump`` with
    ``kind=bug`` but never emits ``/events/emit``, emits the event without
    ``kind`` or ``project_root``, or fails to route bug events into
    ``/next-work`` cannot satisfy this spec. The structural assertion that
    ``bugs`` does not import ``TelecAPIClient`` proves the CLI has no direct
    dispatch boundary at all — not just that no call happened this run.
    """
    assert not hasattr(bugs, "TelecAPIClient"), (
        "bugs CLI must not import TelecAPIClient — the lifecycle router owns dispatch"
    )

    _assert_bug_chain_routes(
        handler=lambda: bugs._handle_bugs_create(["sample-bug"]),
        expected_slug="sample-bug",
    )


def test_bugs_report_does_not_launch_work_session_directly_from_cli() -> None:
    """The CLI must not dispatch a work session itself — the router owns that.

    Structural guard: ``bugs`` must not import ``TelecAPIClient`` at all.
    If the import is present, a future regression could silently re-add
    direct dispatch without any test catching it. Assert the absence of the
    boundary, not just the absence of a call.
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
    """Full-chain spec: ``bugs report`` → ``todo_dumped(kind=bug)`` → router → ``/next-work``.

    Pins the bug-lane chain at the session-launch boundary. The CLI must not
    launch work directly. Instead it must emit ``todo_dumped(kind=bug)``, and
    that emitted envelope is what the lifecycle router handles. A fake API
    client captures the router's launch so the test can assert that the
    router — not the CLI — launches ``/next-work`` with the bug slug.

    A broken implementation that tags the dump request as ``bug`` but never
    emits ``todo_dumped``, emits it without ``kind``, or fails to route bug
    events into ``/next-work`` cannot satisfy this spec. The structural
    assertion that ``bugs`` does not import ``TelecAPIClient`` proves the
    CLI has no direct dispatch boundary at all.
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
