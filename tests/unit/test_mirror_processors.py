"""Unit tests for mirror processors and event handlers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload, SessionLifecycleContext
from teleclaude.mirrors import event_handlers, processors
from teleclaude.mirrors.processors import MirrorEvent
from teleclaude.mirrors.store import SessionMirrorContext


def test_register_processor_is_idempotent_and_returns_a_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(processors, "_processors", [])

    async def sample_processor(event: MirrorEvent) -> None:  # noqa: ARG001 - signature under test
        return None

    processors.register_processor(sample_processor)
    processors.register_processor(sample_processor)

    registered = processors.get_processors()
    registered.append(sample_processor)

    assert processors.get_processors() == [sample_processor]


@pytest.mark.asyncio
async def test_process_mirror_event_skips_when_session_context_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    generate_mirror = AsyncMock()

    monkeypatch.setattr(processors, "resolve_db_path", lambda: "/tmp/teleclaude.db")
    monkeypatch.setattr(processors, "get_session_context", lambda **_: None)
    monkeypatch.setattr(processors, "generate_mirror", generate_mirror)

    await processors.process_mirror_event(MirrorEvent(session_id="sess-1", transcript_path="/tmp/session.jsonl"))

    generate_mirror.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_mirror_event_skips_when_transcript_path_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    generate_mirror = AsyncMock()
    context = SessionMirrorContext(
        session_id="sess-1",
        computer="MozBook",
        agent="claude",
        project="teleclaude",
        transcript_path=None,
    )

    monkeypatch.setattr(processors, "resolve_db_path", lambda: "/tmp/teleclaude.db")
    monkeypatch.setattr(processors, "get_session_context", lambda **_: context)
    monkeypatch.setattr(processors, "generate_mirror", generate_mirror)

    await processors.process_mirror_event(MirrorEvent(session_id="sess-1", transcript_path=None))

    generate_mirror.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_mirror_event_skips_unknown_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    generate_mirror = AsyncMock()
    context = SessionMirrorContext(
        session_id="sess-1",
        computer="MozBook",
        agent="unknown-agent",
        project="teleclaude",
        transcript_path="/tmp/session.jsonl",
    )

    monkeypatch.setattr(processors, "resolve_db_path", lambda: "/tmp/teleclaude.db")
    monkeypatch.setattr(processors, "get_session_context", lambda **_: context)
    monkeypatch.setattr(processors, "generate_mirror", generate_mirror)

    await processors.process_mirror_event(MirrorEvent(session_id="sess-1", transcript_path=None))

    generate_mirror.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_mirror_event_generates_mirror_with_context_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generate_mirror = AsyncMock()
    context = SessionMirrorContext(
        session_id="sess-1",
        computer="",
        agent="claude",
        project="teleclaude",
        transcript_path="/tmp/from-context.jsonl",
    )

    monkeypatch.setattr(processors, "resolve_db_path", lambda: "/tmp/teleclaude.db")
    monkeypatch.setattr(processors, "get_session_context", lambda **_: context)
    monkeypatch.setattr(processors, "generate_mirror", generate_mirror)
    monkeypatch.setattr(processors, "config", SimpleNamespace(computer=SimpleNamespace(name="FallbackBox")))

    await processors.process_mirror_event(MirrorEvent(session_id="sess-1", transcript_path=None))

    generate_mirror.assert_awaited_once_with(
        session_id="sess-1",
        transcript_path="/tmp/from-context.jsonl",
        agent_name=processors.AgentName.CLAUDE,
        computer="FallbackBox",
        project="teleclaude",
        db="/tmp/teleclaude.db",
    )


@pytest.mark.asyncio
async def test_dispatch_isolates_processor_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def bad_processor(event: MirrorEvent) -> None:  # noqa: ARG001 - signature under test
        calls.append("bad")
        raise RuntimeError("boom")

    async def good_processor(event: MirrorEvent) -> None:
        calls.append(f"good:{event.session_id}")

    logger_error = Mock()
    monkeypatch.setattr(event_handlers, "get_processors", lambda: [bad_processor, good_processor])
    monkeypatch.setattr(event_handlers.logger, "error", logger_error)

    await event_handlers._dispatch(MirrorEvent(session_id="sess-1", transcript_path="/tmp/session.jsonl"))

    assert calls == ["bad", "good:sess-1"]
    logger_error.assert_called_once()


@pytest.mark.asyncio
async def test_handle_agent_stop_dispatches_transcript_path(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch = AsyncMock()
    monkeypatch.setattr(event_handlers, "_dispatch", dispatch)

    context = AgentEventContext(
        session_id="sess-1",
        event_type=AgentHookEvents.AGENT_STOP,
        data=AgentStopPayload(session_id="sess-1", transcript_path="/tmp/session.jsonl"),
    )

    await event_handlers.handle_agent_stop(context)

    dispatch.assert_awaited_once_with(MirrorEvent(session_id="sess-1", transcript_path="/tmp/session.jsonl"))


@pytest.mark.asyncio
async def test_handle_session_closed_dispatches_session_only(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch = AsyncMock()
    monkeypatch.setattr(event_handlers, "_dispatch", dispatch)

    await event_handlers.handle_session_closed(SessionLifecycleContext(session_id="sess-1"))

    dispatch.assert_awaited_once_with(MirrorEvent(session_id="sess-1", transcript_path=None))
