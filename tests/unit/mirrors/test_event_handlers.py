from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.core.events import AgentEventContext, SessionLifecycleContext
from teleclaude.mirrors import event_handlers as event_handlers_module
from teleclaude.mirrors.processors import MirrorEvent

pytestmark = pytest.mark.unit


class TestDispatch:
    async def test_dispatch_continues_when_one_processor_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen_events: list[MirrorEvent] = []
        logged_errors: list[Exception] = []

        async def successful_processor(event: MirrorEvent) -> None:
            seen_events.append(event)

        async def failing_processor(event: MirrorEvent) -> None:
            raise RuntimeError("boom")

        def fake_error(message: str, exc: Exception, exc_info: object = None) -> None:
            logged_errors.append(exc)

        monkeypatch.setattr(event_handlers_module, "get_processors", lambda: [successful_processor, failing_processor])
        monkeypatch.setattr(event_handlers_module.logger, "error", fake_error)

        event = MirrorEvent(session_id="session-1", transcript_path="/tmp/transcript.jsonl")
        await event_handlers_module._dispatch(event)

        assert seen_events == [event]
        assert len(logged_errors) == 1
        assert isinstance(logged_errors[0], RuntimeError)


class TestPublicHandlers:
    async def test_handle_agent_stop_dispatches_transcript_path_from_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dispatched_events: list[MirrorEvent] = []

        async def fake_dispatch(event: MirrorEvent) -> None:
            dispatched_events.append(event)

        monkeypatch.setattr(event_handlers_module, "_dispatch", fake_dispatch)

        context = AgentEventContext(
            session_id="session-1",
            data=SimpleNamespace(transcript_path="/tmp/transcript.jsonl"),
            event_type=SimpleNamespace(),
        )
        await event_handlers_module.handle_agent_stop(context)

        assert dispatched_events == [MirrorEvent(session_id="session-1", transcript_path="/tmp/transcript.jsonl")]

    async def test_handle_session_closed_dispatches_without_transcript_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dispatched_events: list[MirrorEvent] = []

        async def fake_dispatch(event: MirrorEvent) -> None:
            dispatched_events.append(event)

        monkeypatch.setattr(event_handlers_module, "_dispatch", fake_dispatch)

        await event_handlers_module.handle_session_closed(SessionLifecycleContext(session_id="session-1"))

        assert dispatched_events == [MirrorEvent(session_id="session-1", transcript_path=None)]
