"""Characterization tests for teleclaude.core.voice_message_handler."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.constants import (
    VOICE_TRANSCRIPTION_STATE_IN_PROGRESS,
    VOICE_TRANSCRIPTION_STATE_INTERRUPTED,
    VOICE_TRANSCRIPTION_STATE_SUCCEEDED,
)
from teleclaude.core import voice_message_handler
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.models import CleanupTrigger
from teleclaude.core.task_registry import TaskRegistry
from teleclaude.core.voice_message_handler import (
    DEFAULT_TRANSCRIBE_LANGUAGE,
    handle_voice,
    init_voice_handler,
    transcribe_voice_with_retry,
)


class TestDefaultTranscribeLanguage:
    @pytest.mark.unit
    def test_default_language_value(self):
        assert DEFAULT_TRANSCRIBE_LANGUAGE == "en"


class TestTranscribeVoiceWithRetry:
    @pytest.mark.unit
    async def test_returns_text_on_success(self):
        with patch(
            "teleclaude.core.voice_message_handler.transcribe_voice",
            new=AsyncMock(return_value="hello world"),
        ):
            text, error = await transcribe_voice_with_retry("/tmp/audio.ogg")
        assert text == "hello world"
        assert error is None

    @pytest.mark.unit
    async def test_returns_none_on_all_failures(self):
        with patch(
            "teleclaude.core.voice_message_handler.transcribe_voice",
            new=AsyncMock(side_effect=RuntimeError("STT failed")),
        ):
            text, error = await transcribe_voice_with_retry("/tmp/audio.ogg", max_retries=0)
        assert text is None
        assert error is not None

    @pytest.mark.unit
    async def test_succeeds_on_second_attempt(self):
        call_count = 0

        async def flaky_transcribe(path: str, lang: str | None = None) -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient error")
            return "transcribed text"

        with patch(
            "teleclaude.core.voice_message_handler.transcribe_voice",
            new=flaky_transcribe,
        ):
            text, error = await transcribe_voice_with_retry("/tmp/audio.ogg", max_retries=1)
        assert text == "transcribed text"
        assert error is None

    @pytest.mark.unit
    async def test_returns_failure_when_transcription_exceeds_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def hanging_transcribe(path: str, lang: str | None = None) -> str:
            await asyncio.Event().wait()
            return "unreachable"

        monkeypatch.setattr(voice_message_handler, "VOICE_TRANSCRIPTION_TIMEOUT_S", 0.01, raising=False)
        monkeypatch.setattr(voice_message_handler, "transcribe_voice", hanging_transcribe)

        text, error = await asyncio.wait_for(
            transcribe_voice_with_retry("/tmp/audio.ogg", max_retries=0),
            timeout=0.1,
        )

        assert text is None
        assert error is not None


class TestInitVoiceHandler:
    @pytest.mark.unit
    def test_init_with_api_key_sets_env_var(self):
        # Ensure the env var is not already set to a conflicting value
        original = os.environ.pop("OPENAI_API_KEY", None)
        try:
            init_voice_handler(api_key="test-key-123")
            assert os.environ.get("OPENAI_API_KEY") == "test-key-123"
        finally:
            if original is not None:
                os.environ["OPENAI_API_KEY"] = original
            else:
                os.environ.pop("OPENAI_API_KEY", None)

    @pytest.mark.unit
    def test_init_without_api_key_does_not_raise(self):
        # Should be a no-op, not raise
        init_voice_handler()


class TestHandleVoicePersistence:
    @pytest.mark.unit
    async def test_persists_notice_id_and_edits_placeholder_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session_id = "session-1"
        notice_message_id = "notice-1"
        transcription_text = "transcribed text"
        actor_id = "actor-1"
        actor_name = "Actor"
        actor_avatar_url = "https://example.invalid/avatar.png"
        audio_path = tmp_path / "voice.ogg"
        audio_path.write_bytes(b"audio")
        calls: list[tuple[str, object]] = []
        created_actor_metadata: list[tuple[object | None, object | None, object | None]] = []
        row = SimpleNamespace(id=7)
        session = SimpleNamespace(tmux_session_name="tmux-session")

        async def create_voice_transcription(**kwargs: object) -> SimpleNamespace:
            created_actor_metadata.append(
                (kwargs.get("actor_id"), kwargs.get("actor_name"), kwargs.get("actor_avatar_url"))
            )
            calls.append(("create", bool(kwargs.get("actor_name"))))
            return row

        async def set_notice(transcription_id: int, value: str | None) -> bool:
            calls.append(("notice", (transcription_id, value is notice_message_id)))
            return True

        async def update_state(transcription_id: int, state: str, *, last_error: str | None = None) -> bool:
            calls.append(("state", (transcription_id, state, last_error)))
            return True

        async def send_message(_session_id: str, message: str, _metadata: object) -> str | None:
            calls.append(("send", bool(message)))
            return notice_message_id

        async def edit_message(_session_id: str, message_id: str, message: str, _metadata: object) -> bool:
            calls.append(("edit", (message_id is notice_message_id, message is transcription_text)))
            return True

        async def transcribe(_path: str, *, language: str | None = None) -> tuple[str | None, str | None]:
            calls.append(("transcribe", language))
            return transcription_text, None

        fake_db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            create_voice_transcription=create_voice_transcription,
            set_voice_transcription_notice_message_id=set_notice,
            update_voice_transcription_state=update_state,
        )
        monkeypatch.setattr(voice_message_handler, "db", fake_db)
        monkeypatch.setattr(voice_message_handler.tmux_bridge, "is_process_running", AsyncMock(return_value=True))
        monkeypatch.setattr(voice_message_handler, "transcribe_voice_with_retry", transcribe)

        result = await handle_voice(
            session_id=session_id,
            audio_path=str(audio_path),
            context=VoiceEventContext(
                session_id=session_id,
                file_path=str(audio_path),
                origin="discord",
                actor_id=actor_id,
                actor_name=actor_name,
                actor_avatar_url=actor_avatar_url,
            ),
            send_message=send_message,
            edit_message=edit_message,
        )

        assert result is transcription_text
        assert created_actor_metadata == [(actor_id, actor_name, actor_avatar_url)]
        assert calls == [
            ("create", True),
            ("send", True),
            ("notice", (row.id, True)),
            ("state", (row.id, VOICE_TRANSCRIPTION_STATE_IN_PROGRESS, None)),
            ("transcribe", DEFAULT_TRANSCRIBE_LANGUAGE),
            ("state", (row.id, VOICE_TRANSCRIPTION_STATE_SUCCEEDED, None)),
            ("edit", (True, True)),
        ]
        assert not audio_path.exists()

    @pytest.mark.unit
    async def test_overlong_transcription_uses_overflow_send_and_deletes_placeholder(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session_id = "session-1"
        notice_message_id = "notice-1"
        audio_path = tmp_path / "voice.ogg"
        audio_path.write_bytes(b"audio")
        row = SimpleNamespace(id=17)
        session = SimpleNamespace(tmux_session_name="tmux-session")
        transcription_text = "x" * (voice_message_handler.VOICE_TRANSCRIPTION_NOTICE_EDIT_MAX_CHARS + 1)
        sent: list[tuple[int, bool, str | None]] = []
        edits: list[bool] = []
        deleted: list[str] = []

        async def send_message(_session_id: str, message: str, metadata: object) -> str | None:
            sent.append(
                (
                    len(message),
                    bool(getattr(metadata, "is_transcription", False)),
                    getattr(metadata, "cleanup_trigger", None),
                )
            )
            return notice_message_id if len(sent) == 1 else "transcription-1"

        async def edit_message(_session_id: str, _message_id: str, _message: str, _metadata: object) -> bool:
            edits.append(True)
            return True

        async def delete_message(_session_id: str, message_id: str) -> None:
            deleted.append(message_id)

        async def transcribe(_path: str, *, language: str | None = None) -> tuple[str | None, str | None]:
            del language
            return transcription_text, None

        fake_db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            create_voice_transcription=AsyncMock(return_value=row),
            set_voice_transcription_notice_message_id=AsyncMock(return_value=True),
            update_voice_transcription_state=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(voice_message_handler, "db", fake_db)
        monkeypatch.setattr(voice_message_handler.tmux_bridge, "is_process_running", AsyncMock(return_value=True))
        monkeypatch.setattr(voice_message_handler, "transcribe_voice_with_retry", transcribe)

        result = await handle_voice(
            session_id=session_id,
            audio_path=str(audio_path),
            context=VoiceEventContext(session_id=session_id, file_path=str(audio_path), origin="discord"),
            send_message=send_message,
            edit_message=edit_message,
            delete_message=delete_message,
        )

        assert result is transcription_text
        assert edits == []
        assert sent[0][0] > 0
        assert sent[0][1:] == (False, CleanupTrigger.NEXT_NOTICE.value)
        assert sent[1] == (len(transcription_text), True, CleanupTrigger.NEXT_TURN.value)
        assert len(deleted) == 1
        assert deleted[0] is notice_message_id

    @pytest.mark.unit
    async def test_failed_resolution_edit_uses_send_fallback_and_deletes_placeholder(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session_id = "session-1"
        notice_message_id = "notice-1"
        audio_path = tmp_path / "voice.ogg"
        audio_path.write_bytes(b"audio")
        row = SimpleNamespace(id=18)
        session = SimpleNamespace(tmux_session_name="tmux-session")
        sent_transcriptions: list[bool] = []
        edited: list[str] = []
        deleted: list[str] = []

        async def send_message(_session_id: str, _message: str, metadata: object) -> str | None:
            sent_transcriptions.append(bool(getattr(metadata, "is_transcription", False)))
            return notice_message_id if len(sent_transcriptions) == 1 else "transcription-1"

        async def edit_message(_session_id: str, message_id: str, _message: str, _metadata: object) -> bool:
            edited.append(message_id)
            return False

        async def delete_message(_session_id: str, message_id: str) -> None:
            deleted.append(message_id)

        async def transcribe(_path: str, *, language: str | None = None) -> tuple[str | None, str | None]:
            del language
            return "transcribed text", None

        fake_db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            create_voice_transcription=AsyncMock(return_value=row),
            set_voice_transcription_notice_message_id=AsyncMock(return_value=True),
            update_voice_transcription_state=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(voice_message_handler, "db", fake_db)
        monkeypatch.setattr(voice_message_handler.tmux_bridge, "is_process_running", AsyncMock(return_value=True))
        monkeypatch.setattr(voice_message_handler, "transcribe_voice_with_retry", transcribe)

        await handle_voice(
            session_id=session_id,
            audio_path=str(audio_path),
            context=VoiceEventContext(session_id=session_id, file_path=str(audio_path), origin="discord"),
            send_message=send_message,
            edit_message=edit_message,
            delete_message=delete_message,
        )

        assert len(edited) == 1
        assert edited[0] is notice_message_id
        assert sent_transcriptions == [False, True]
        assert len(deleted) == 1
        assert deleted[0] is notice_message_id

    @pytest.mark.unit
    async def test_recovery_reuses_existing_notice_without_creating_new_row(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session_id = "session-1"
        notice_message_id = "notice-1"
        transcription_text = "recovered text"
        audio_path = tmp_path / "voice.ogg"
        audio_path.write_bytes(b"audio")
        calls: list[tuple[str, object]] = []
        row = SimpleNamespace(id=9)
        session = SimpleNamespace(tmux_session_name="tmux-session")

        async def update_state(transcription_id: int, state: str, *, last_error: str | None = None) -> bool:
            calls.append(("state", (transcription_id, state, last_error)))
            return True

        async def send_message(_session_id: str, message: str, _metadata: object) -> str | None:
            calls.append(("send", bool(message)))
            return "unexpected"

        async def edit_message(_session_id: str, message_id: str, message: str, _metadata: object) -> bool:
            calls.append(("edit", (message_id, message == transcription_text)))
            return True

        async def transcribe(_path: str, *, language: str | None = None) -> tuple[str | None, str | None]:
            calls.append(("transcribe", language))
            return transcription_text, None

        fake_db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            create_voice_transcription=AsyncMock(),
            get_voice_transcription=AsyncMock(return_value=row),
            set_voice_transcription_notice_message_id=AsyncMock(return_value=True),
            update_voice_transcription_state=update_state,
        )
        monkeypatch.setattr(voice_message_handler, "db", fake_db)
        monkeypatch.setattr(voice_message_handler.tmux_bridge, "is_process_running", AsyncMock(return_value=True))
        monkeypatch.setattr(voice_message_handler, "transcribe_voice_with_retry", transcribe)

        result = await handle_voice(
            session_id=session_id,
            audio_path=str(audio_path),
            context=VoiceEventContext(
                session_id=session_id,
                file_path=str(audio_path),
                origin="discord",
                voice_transcription_id=row.id,
                notice_message_id=notice_message_id,
            ),
            send_message=send_message,
            edit_message=edit_message,
        )

        assert result == transcription_text
        fake_db.create_voice_transcription.assert_not_awaited()
        fake_db.set_voice_transcription_notice_message_id.assert_not_awaited()
        assert calls == [
            ("edit", (notice_message_id, False)),
            ("state", (row.id, VOICE_TRANSCRIPTION_STATE_IN_PROGRESS, None)),
            ("transcribe", DEFAULT_TRANSCRIBE_LANGUAGE),
            ("state", (row.id, VOICE_TRANSCRIPTION_STATE_SUCCEEDED, None)),
            ("edit", (notice_message_id, True)),
        ]
        assert not audio_path.exists()

    @pytest.mark.unit
    async def test_cancellation_marks_interrupted_and_edits_existing_notice(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session_id = "session-1"
        notice_message_id = "notice-1"
        audio_path = tmp_path / "voice.ogg"
        audio_path.write_bytes(b"audio")
        row = SimpleNamespace(id=8)
        session = SimpleNamespace(tmux_session_name="tmux-session")
        started = asyncio.Event()
        sends: list[bool] = []
        edits: list[tuple[str, bool]] = []
        states: list[str] = []

        async def transcribe(_path: str, *, language: str | None = None) -> tuple[str | None, str | None]:
            del language
            started.set()
            await asyncio.Event().wait()
            return None, None

        async def send_message(_session_id: str, message: str, _metadata: object) -> str | None:
            sends.append(bool(message))
            return notice_message_id

        async def edit_message(_session_id: str, message_id: str, message: str, _metadata: object) -> bool:
            edits.append((message_id, bool(message)))
            return True

        fake_db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            create_voice_transcription=AsyncMock(return_value=row),
            set_voice_transcription_notice_message_id=AsyncMock(return_value=True),
            update_voice_transcription_state=AsyncMock(
                side_effect=lambda _row_id, state, **_kwargs: states.append(state) or True
            ),
        )
        monkeypatch.setattr(voice_message_handler, "db", fake_db)
        monkeypatch.setattr(voice_message_handler.tmux_bridge, "is_process_running", AsyncMock(return_value=True))
        monkeypatch.setattr(voice_message_handler, "transcribe_voice_with_retry", transcribe)

        registry = TaskRegistry()
        task = registry.spawn(
            handle_voice(
                session_id=session_id,
                audio_path=str(audio_path),
                context=VoiceEventContext(session_id=session_id, file_path=str(audio_path), origin="discord"),
                send_message=send_message,
                edit_message=edit_message,
            ),
            name="voice-test",
        )

        await asyncio.wait_for(started.wait(), timeout=0.2)
        await registry.shutdown(timeout=1.0)

        assert task.cancelled()
        assert states == [VOICE_TRANSCRIPTION_STATE_IN_PROGRESS, VOICE_TRANSCRIPTION_STATE_INTERRUPTED]
        assert sends == [True]
        assert edits == [(notice_message_id, True)]
        assert audio_path.exists()
