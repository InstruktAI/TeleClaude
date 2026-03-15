"""Characterization tests for teleclaude.services.headless_snapshot_service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.models import Session
from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService


def _make_session(transcript_path: str) -> Session:
    return Session(
        session_id="session-1",
        computer_name="local",
        tmux_session_name="tmux-1",
        title="Test Session",
        native_log_file=transcript_path,
        active_agent="claude",
    )


class TestHeadlessSnapshotService:
    @pytest.mark.unit
    async def test_skips_missing_transcript_file(self, tmp_path: Path) -> None:
        service = HeadlessSnapshotService()
        client = AsyncMock()
        session = _make_session(str(tmp_path / "missing.md"))

        await service.send_snapshot(session, reason="turn-complete", client=client)

        client.send_output_update.assert_not_awaited()
        assert service._last_headless_snapshot_fingerprint == {}

    @pytest.mark.unit
    async def test_first_snapshot_sends_only_tail_after_max_chars(self, tmp_path: Path) -> None:
        transcript = tmp_path / "transcript.md"
        transcript.write_text("raw transcript", encoding="utf-8")
        service = HeadlessSnapshotService()
        client = AsyncMock()
        session = _make_session(str(transcript))
        parsed_markdown = "x" * (UI_MESSAGE_MAX_CHARS + 7)

        with patch(
            "teleclaude.services.headless_snapshot_service.parse_session_transcript",
            return_value=parsed_markdown,
        ) as parse_mock:
            await service.send_snapshot(session, reason="turn-complete", client=client)

        parse_mock.assert_called_once()
        assert parse_mock.call_args.args == (str(transcript), "Test Session")
        assert parse_mock.call_args.kwargs["tail_chars"] == 0
        assert parse_mock.call_args.kwargs["escape_triple_backticks"] is True
        sent_args = client.send_output_update.await_args.args
        assert sent_args[0] is session
        assert sent_args[1] == parsed_markdown[UI_MESSAGE_MAX_CHARS:]
        assert client.send_output_update.await_args.kwargs["render_markdown"] is True

    @pytest.mark.unit
    async def test_skips_duplicate_fingerprint(self, tmp_path: Path) -> None:
        transcript = tmp_path / "transcript.md"
        transcript.write_text("raw transcript", encoding="utf-8")
        service = HeadlessSnapshotService()
        client = AsyncMock()
        session = _make_session(str(transcript))
        parsed_markdown = "x" * (UI_MESSAGE_MAX_CHARS + 3)

        with patch(
            "teleclaude.services.headless_snapshot_service.parse_session_transcript",
            return_value=parsed_markdown,
        ) as parse_mock:
            await service.send_snapshot(session, reason="first", client=client)
            await service.send_snapshot(session, reason="duplicate", client=client)

        assert parse_mock.call_count == 1
        client.send_output_update.assert_awaited_once()
