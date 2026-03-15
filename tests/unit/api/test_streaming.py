"""Characterization tests for streaming SSE route behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import streaming
from teleclaude.api.streaming import ChatStreamMessage, ChatStreamRequest
from teleclaude.core.db_models import Session
from teleclaude.core.models import JsonDict


def _make_request() -> SimpleNamespace:
    return SimpleNamespace(headers={})


def _make_session(
    *,
    session_id: str = "sess-1",
    lifecycle_status: str | None = "active",
    native_log_file: str | None = None,
    transcript_files: str | None = "[]",
    active_agent: str | None = "claude",
) -> Session:
    return Session(
        session_id=session_id,
        computer_name="local-box",
        lifecycle_status=lifecycle_status,
        native_log_file=native_log_file,
        transcript_files=transcript_files,
        active_agent=active_agent,
    )


async def _collect_stream(response: object) -> list[str]:
    chunks: list[str] = []
    body_iterator = response.body_iterator
    async for chunk in body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return chunks


def _parse_sse_event(chunk: str) -> JsonDict | str:
    prefix = "data: "
    assert chunk.startswith(prefix)
    payload = chunk.removeprefix(prefix).strip()
    if payload == "[DONE]":
        return payload
    loaded = json.loads(payload)
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.unit
@pytest.mark.asyncio
class TestStreamingRoute:
    @pytest.mark.parametrize(
        ("lifecycle_status", "expected_status"),
        [
            ("active", "streaming"),
            ("completed", "completed"),
            ("error", "error"),
            ("closed", "closed"),
            (None, "streaming"),
        ],
    )
    async def test_chat_stream_maps_lifecycle_status_to_session_status_event(
        self,
        lifecycle_status: str | None,
        expected_status: str,
    ) -> None:
        """Initial session-status SSE uses the canonical lifecycle mapping."""
        session = _make_session(lifecycle_status=lifecycle_status)

        with patch("teleclaude.api.streaming.db.get_session", new=AsyncMock(return_value=session)):
            response = await streaming.chat_stream(_make_request(), ChatStreamRequest(sessionId=session.session_id))
            events = [_parse_sse_event(chunk) for chunk in await _collect_stream(response)]

        assert events[1] == {
            "type": "data-session-status",
            "sessionId": session.session_id,
            "status": expected_status,
        }

    async def test_chat_stream_finishes_immediately_when_no_live_transcript_is_available(
        self,
        tmp_path: Path,
    ) -> None:
        """Missing transcript files take the direct finish path without live polling."""
        session = _make_session(native_log_file=str(tmp_path / "missing.jsonl"))

        with patch("teleclaude.api.streaming.db.get_session", new=AsyncMock(return_value=session)):
            response = await streaming.chat_stream(_make_request(), ChatStreamRequest(sessionId=session.session_id))
            events = [_parse_sse_event(chunk) for chunk in await _collect_stream(response)]

        payloads = [event for event in events if isinstance(event, dict)]

        assert [payload["type"] for payload in payloads] == ["start", "data-session-status", "finish"]
        assert payloads[0]["messageId"] == payloads[-1]["messageId"]
        assert events[-1] == "[DONE]"

    async def test_chat_stream_emits_live_transcript_entries_before_closing(self, tmp_path: Path) -> None:
        """Live transcript appends are projected into SSE before the stream closes."""
        live_file = tmp_path / "session.jsonl"
        live_file.write_text("", encoding="utf-8")
        active_session = _make_session(native_log_file=str(live_file))
        closed_session = _make_session(
            session_id=active_session.session_id,
            lifecycle_status="closed",
            native_log_file=str(live_file),
        )
        live_entry = {
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "delta"}],
            }
        }
        sleep_calls = 0

        async def _fake_sleep(_: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 1:
                live_file.write_text(json.dumps(live_entry) + "\n", encoding="utf-8")

        with (
            patch(
                "teleclaude.api.streaming.db.get_session",
                new=AsyncMock(side_effect=[active_session, active_session, closed_session]),
            ),
            patch("teleclaude.api.streaming.asyncio.sleep", new=_fake_sleep),
        ):
            response = await streaming.chat_stream(
                _make_request(), ChatStreamRequest(sessionId=active_session.session_id)
            )
            events = [_parse_sse_event(chunk) for chunk in await _collect_stream(response)]

        payloads = [event for event in events if isinstance(event, dict)]

        assert [payload["type"] for payload in payloads] == [
            "start",
            "data-session-status",
            "text-start",
            "text-delta",
            "text-end",
            "data-session-status",
            "finish",
        ]
        assert payloads[1]["status"] == "streaming"
        assert payloads[-2]["status"] == "closed"
        assert events[-1] == "[DONE]"

    async def test_chat_stream_raises_404_when_session_is_missing(self) -> None:
        """Route returns a not-found error before constructing a stream for unknown sessions."""
        with patch("teleclaude.api.streaming.db.get_session", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_info:
                await streaming.chat_stream(_make_request(), ChatStreamRequest(sessionId="missing-session"))

        assert exc_info.value.status_code == 404

    async def test_chat_stream_returns_sse_response_with_latest_user_message_wired_through(self) -> None:
        """Route forwards request fields into the stream generator and preserves SSE headers."""
        session = _make_session()

        async def _fake_stream():
            yield "data: [DONE]\n\n"

        stream_factory = MagicMock(return_value=_fake_stream())

        with (
            patch("teleclaude.api.streaming.db.get_session", new=AsyncMock(return_value=session)),
            patch("teleclaude.api.streaming._stream_sse", new=stream_factory),
        ):
            response = await streaming.chat_stream(
                _make_request(),
                ChatStreamRequest(
                    sessionId=session.session_id,
                    since_timestamp="2025-03-15T12:00:00Z",
                    messages=[
                        ChatStreamMessage(role="assistant", content="ignored-assistant"),
                        ChatStreamMessage(role="user", content="   "),
                        ChatStreamMessage(role="user", content="latest-user"),
                    ],
                ),
            )
            chunks = await _collect_stream(response)

        assert response.media_type == "text/event-stream"
        assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["connection"] == "keep-alive"
        assert chunks == ["data: [DONE]\n\n"]
        stream_factory.assert_called_once_with(
            session=session,
            session_id=session.session_id,
            since_timestamp="2025-03-15T12:00:00Z",
            user_message="latest-user",
        )
