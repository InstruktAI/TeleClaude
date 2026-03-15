from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.adapters.discord.input_handlers import InputHandlersMixin

pytestmark = pytest.mark.unit


class ThreadChannel:
    def __init__(self, channel_id: str, parent_id: str | None) -> None:
        self.id = channel_id
        self.parent_id = parent_id
        self.parent = None if parent_id is None else SimpleNamespace(id=parent_id)


class PlainChannel:
    def __init__(self, channel_id: str) -> None:
        self.id = channel_id
        self.parent_id = None
        self.parent = None


class DummyInputHandlers(InputHandlersMixin):
    def __init__(self) -> None:
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )


def test_extract_audio_attachment_returns_first_audio_content_type() -> None:
    adapter = DummyInputHandlers()
    message = SimpleNamespace(
        attachments=[
            SimpleNamespace(filename="voice.mp3", content_type="audio/mpeg"),
            SimpleNamespace(filename="note.wav", content_type="audio/wav"),
        ]
    )

    attachment = adapter._extract_audio_attachment(message)

    assert attachment.filename == "voice.mp3"


def test_extract_file_attachments_excludes_audio_but_keeps_unknown_content_types() -> None:
    adapter = DummyInputHandlers()
    message = SimpleNamespace(
        attachments=[
            SimpleNamespace(filename="voice.mp3", content_type="audio/mpeg"),
            SimpleNamespace(filename="report.txt", content_type="text/plain"),
            SimpleNamespace(filename="image.png", content_type=None),
        ]
    )

    attachments = adapter._extract_file_attachments(message)

    assert [attachment.filename for attachment in attachments] == ["report.txt", "image.png"]


def test_is_thread_channel_uses_class_name_contains_thread() -> None:
    adapter = DummyInputHandlers()

    assert adapter._is_thread_channel(ThreadChannel("500", "100")) is True
    assert adapter._is_thread_channel(PlainChannel("600")) is False


def test_extract_channel_ids_uses_parent_for_threads_and_self_for_plain_channels() -> None:
    adapter = DummyInputHandlers()

    assert adapter._extract_channel_ids(SimpleNamespace(channel=ThreadChannel("500", "100"))) == (100, 500)
    assert adapter._extract_channel_ids(SimpleNamespace(channel=ThreadChannel("700", None))) == (700, 700)
    assert adapter._extract_channel_ids(SimpleNamespace(channel=PlainChannel("600"))) == (600, None)
