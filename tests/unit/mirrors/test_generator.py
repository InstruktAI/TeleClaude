# pyright: reportUnknownLambdaType=false
# pylint: disable=protected-access
from __future__ import annotations

from typing import Any, cast

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.mirrors import generator as generator_module
from teleclaude.mirrors.store import MirrorRecord
from teleclaude.utils.transcript import StructuredMessage

pytestmark = pytest.mark.unit


def _message(
    role: str, message_type: str, text: str, timestamp: str = "2025-01-01T00:00:00+00:00"
) -> StructuredMessage:
    return StructuredMessage(role=role, type=message_type, text=text, timestamp=timestamp)


def _existing_record() -> MirrorRecord:
    return MirrorRecord(
        session_id="session-1",
        source_identity="claude:alpha/session-1.jsonl",
        computer="mac",
        agent="claude",
        project="alpha",
        title="Existing title",
        timestamp_start="2025-01-01T00:00:00+00:00",
        timestamp_end="2025-01-01T00:01:00+00:00",
        conversation_text="User: hi",
        message_count=1,
        metadata={"transcript_path": "/tmp/transcript.jsonl"},
        created_at="2024-12-31T23:59:00+00:00",
        updated_at="2025-01-01T00:01:00+00:00",
    )


class TestRenderConversation:
    def test_render_conversation_includes_timestamp_prefix_when_present(self) -> None:
        messages = [
            _message("user", "text", "Hello", "2025-01-01T10:00:00+00:00"),
            _message("assistant", "text", "Hi there", "2025-01-01T10:01:00+00:00"),
        ]
        result = generator_module._render_conversation(messages)
        assert result == "[2025-01-01T10:00:00+00:00] User: Hello\n\n[2025-01-01T10:01:00+00:00] Assistant: Hi there"

    def test_render_conversation_omits_timestamp_prefix_when_none(self) -> None:
        messages = [
            StructuredMessage(role="user", type="text", text="Hello", timestamp=None),
            StructuredMessage(role="assistant", type="text", text="Hi there", timestamp=None),
        ]
        result = generator_module._render_conversation(messages)
        assert result == "User: Hello\n\nAssistant: Hi there"

    def test_render_conversation_includes_timestamp_prefix_when_empty_string(self) -> None:
        """Empty string timestamp is not None — the prefix is rendered explicitly."""
        messages = [
            StructuredMessage(role="user", type="text", text="Hello", timestamp=""),
            StructuredMessage(role="assistant", type="text", text="Hi there", timestamp=""),
        ]
        result = generator_module._render_conversation(messages)
        assert result == "[] User: Hello\n\n[] Assistant: Hi there"

    def test_render_conversation_handles_mixed_timestamp_presence(self) -> None:
        messages = [
            _message("user", "text", "Hello", "2025-01-01T10:00:00+00:00"),
            StructuredMessage(role="assistant", type="text", text="Hi there", timestamp=None),
        ]
        result = generator_module._render_conversation(messages)
        assert result == "[2025-01-01T10:00:00+00:00] User: Hello\n\nAssistant: Hi there"


class TestNormalizeConversationMessages:
    def test_normalize_conversation_messages_keeps_user_and_assistant_text(self) -> None:
        normalized = generator_module._normalize_conversation_messages(
            [
                _message("user", "text", "  <system-reminder>ignore me</system-reminder> Keep this "),
                _message("assistant", "text", "  Response text  "),
                _message("assistant", "tool_use", "skip tool"),
                _message("system", "text", "skip system"),
            ]
        )

        assert [(message.role, message.text) for message in normalized] == [
            ("user", "Keep this"),
            ("assistant", "Response text"),
        ]


class TestGenerateMirrorSync:
    def test_generate_mirror_sync_deletes_existing_record_when_no_conversation_remains(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        deleted: list[tuple[str | None, str | None]] = []

        monkeypatch.setattr(
            generator_module,
            "extract_structured_messages",
            lambda *args, **kwargs: [_message("system", "thinking", "skip")],
        )
        monkeypatch.setattr(
            generator_module,
            "delete_mirror",
            lambda session_id=None, source_identity=None, db=None: deleted.append((session_id, source_identity)),
        )

        generated = generator_module.generate_mirror_sync(
            session_id="session-1",
            source_identity="claude:alpha/session-1.jsonl",
            transcript_path="/tmp/transcript.jsonl",
            agent_name=AgentName.CLAUDE,
            computer="mac",
            project="alpha",
            db=None,
        )

        assert generated is False
        assert deleted == [("session-1", "claude:alpha/session-1.jsonl")]

    def test_generate_mirror_sync_upserts_normalized_conversation_and_preserves_created_at(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upserted_records: list[MirrorRecord] = []

        monkeypatch.setattr(
            generator_module,
            "extract_structured_messages",
            lambda *args, **kwargs: [
                _message("user", "text", "Plan the rollout", "2025-01-01T00:00:00+00:00"),
                _message("assistant", "text", "Here is the rollout", "2025-01-01T00:01:00+00:00"),
            ],
        )
        monkeypatch.setattr(generator_module, "get_mirror", lambda source_identity=None, db=None: _existing_record())
        monkeypatch.setattr(generator_module, "upsert_mirror", lambda record, db=None: upserted_records.append(record))
        monkeypatch.setattr(generator_module, "_generate_session_summary", lambda conversation_text: None)

        generated = generator_module.generate_mirror_sync(
            session_id="session-1",
            source_identity="claude:alpha/session-1.jsonl",
            transcript_path="/tmp/transcript.jsonl",
            agent_name=AgentName.CLAUDE,
            computer="mac",
            project="alpha",
            db=None,
        )

        assert generated is True
        assert len(upserted_records) == 1
        record = upserted_records[0]
        assert record.created_at == "2024-12-31T23:59:00+00:00"
        assert record.title == "Plan the rollout"
        assert record.message_count == 2
        assert (
            record.conversation_text == "[2025-01-01T00:00:00+00:00] User: Plan the rollout\n\n"
            "[2025-01-01T00:01:00+00:00] Assistant: Here is the rollout"
        )
        assert record.metadata["agent"] == "claude"
        assert record.metadata["transcript_path"] == "/tmp/transcript.jsonl"

    async def test_generate_mirror_offloads_sync_generation_to_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        thread_calls: list[tuple[object, tuple[object, ...], tuple[tuple[str, object], ...]]] = []

        async def fake_to_thread(func: object, *args: object, **kwargs: object) -> bool:
            thread_calls.append((func, args, tuple(kwargs.items())))
            return True

        monkeypatch.setattr(generator_module.asyncio, "to_thread", fake_to_thread)

        generated = await generator_module.generate_mirror(
            session_id="session-1",
            source_identity="claude:alpha/session-1.jsonl",
            transcript_path="/tmp/transcript.jsonl",
            agent_name=AgentName.CLAUDE,
            computer="mac",
            project="alpha",
            db=None,
        )

        assert generated is True
        assert thread_calls[0][0] is generator_module.generate_mirror_sync
        assert ("session_id", "session-1") in thread_calls[0][2]
        assert ("project", "alpha") in thread_calls[0][2]

    async def test_generate_mirror_persists_summary_visibility_and_channel_identifiers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upserted_records: list[MirrorRecord] = []

        monkeypatch.setattr(
            generator_module,
            "extract_structured_messages",
            lambda *args, **kwargs: [
                _message("user", "text", "Customer needs help", "2025-01-01T00:00:00+00:00"),
                _message("assistant", "text", "Resolved issue", "2025-01-01T00:01:00+00:00"),
            ],
        )
        monkeypatch.setattr(generator_module, "get_mirror", lambda source_identity=None, db=None: None)
        monkeypatch.setattr(
            generator_module,
            "_generate_session_summary",
            lambda conversation_text: "Customer asked for help and the issue was resolved.",
        )
        monkeypatch.setattr(generator_module, "upsert_mirror", lambda record, db=None: upserted_records.append(record))

        generated = await cast(Any, generator_module.generate_mirror)(
            session_id="session-1",
            source_identity="telegram:1285425702",
            transcript_path="/tmp/transcript.jsonl",
            agent_name=AgentName.CLAUDE,
            computer="mac",
            project="alpha",
            human_email="customer@example.com",
            visibility="shared",
            last_input_origin="telegram",
            channel_identifiers={"user_id": "1285425702"},
            db=None,
        )

        record = cast(Any, upserted_records[0])
        assert generated is True
        assert record.summary == "Customer asked for help and the issue was resolved."
        assert record.human_email == "customer@example.com"
        assert record.visibility == "shared"
        assert record.metadata["origin_channel"] == "telegram"
        assert record.metadata["user_id"] == "1285425702"
