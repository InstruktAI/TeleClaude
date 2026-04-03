from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from types import SimpleNamespace
from typing import TypedDict, cast
from unittest.mock import AsyncMock, Mock

import pytest

import jobs.session_memory_extraction as job_module
from jobs.session_memory_extraction import SessionMemoryExtractionJob
from teleclaude.core import tmux_bridge as tmux_bridge_module
from teleclaude.memory.types import ObservationType
from teleclaude.mirrors.store import MirrorRecord
from teleclaude.utils.transcript import StructuredMessage

pytestmark = [
    pytest.mark.unit,
]


class _MemoryCandidate(TypedDict):
    type: str
    title: str
    narrative: str
    facts: list[str]


class _ActionableItem(TypedDict):
    type: str
    summary: str


class _PublishedPayload(TypedDict):
    type: str
    summary: str
    session_id: str


@dataclass(frozen=True)
class _PublishedMessage:
    redis: object
    channel: str
    payload: _PublishedPayload


class _FakeChannelsPublisher:
    def __init__(self) -> None:
        self.published_messages: list[_PublishedMessage] = []

    def channel_key(self, project: str, topic: str) -> str:
        return f"channel:{project}:{topic}"

    async def publish(self, redis: object, channel: str, payload: _PublishedPayload) -> str:
        self.published_messages.append(_PublishedMessage(redis=redis, channel=channel, payload=payload))
        return "1-0"


class _SpyProcessSessionJob(SessionMemoryExtractionJob):
    def __init__(self, *, transcript: str | None, identity_key: str | None) -> None:
        self._transcript = transcript
        self._identity_key = identity_key
        self.read_calls: list[tuple[str, datetime | None]] = []
        self.personal_calls: list[tuple[str, str | None, object]] = []
        self.business_calls: list[tuple[str, object]] = []
        self.actionable_calls: list[tuple[str, object]] = []
        self.bookkeeping_calls: list[tuple[str, datetime]] = []

    async def _read_transcript_delta(self, session_id: str, since: datetime | None) -> str | None:
        self.read_calls.append((session_id, since))
        return self._transcript

    def _resolve_identity_key(self, session: object) -> str | None:
        _ = session
        return self._identity_key

    async def _extract_personal_memories(
        self,
        transcript: str,
        identity_key: str | None,
        session: object,
    ) -> None:
        self.personal_calls.append((transcript, identity_key, session))

    async def _extract_business_memories(self, transcript: str, session: object) -> None:
        self.business_calls.append((transcript, session))

    async def _extract_and_publish_actionable_items(self, transcript: str, session: object) -> None:
        self.actionable_calls.append((transcript, session))

    async def _update_bookkeeping(self, session_id: str, now: datetime) -> None:
        self.bookkeeping_calls.append((session_id, now))


def _make_session(
    session_id: str = "session-1",
    *,
    project_path: str = "demo",
    help_desk_processed_at: datetime | None = None,
    last_memory_extraction_at: datetime | None = None,
    tmux_session_name: str | None = "tmux-session-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        project_path=project_path,
        help_desk_processed_at=help_desk_processed_at,
        last_memory_extraction_at=last_memory_extraction_at,
        tmux_session_name=tmux_session_name,
    )


class TestSessionMemoryExtractionJob:
    async def test_get_redis_builds_a_client_from_redis_config_without_using_http_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ping = AsyncMock()
        fake_redis = cast(object, SimpleNamespace(ping=ping))
        from_url = Mock(return_value=fake_redis)
        redis_config = SimpleNamespace(
            enabled=True,
            url="rediss://cache.example:6380/2",
            password="secret",
            max_connections=17,
            socket_timeout=9,
        )
        api_routes = import_module("teleclaude.channels.api_routes")

        monkeypatch.setattr(job_module, "_REDIS_CLIENT", None, raising=False)
        monkeypatch.setattr(job_module, "config", SimpleNamespace(redis=redis_config), raising=False)
        monkeypatch.setattr(job_module.Redis, "from_url", from_url)
        monkeypatch.setattr(
            api_routes,
            "_get_transport",
            Mock(side_effect=AssertionError("job must not depend on HTTP transport state")),
        )

        redis_client = await job_module.get_redis()

        assert redis_client is fake_redis
        from_url.assert_called_once_with(
            "rediss://cache.example:6380/2",
            password="secret",
            max_connections=17,
            socket_timeout=9,
            health_check_interval=10,
            decode_responses=False,
            ssl_cert_reqs=job_module.ssl.CERT_NONE,
        )
        ping.assert_awaited_once_with()

    async def test_read_transcript_delta_returns_only_messages_after_last_extraction_boundary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        since = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
        mirror = MirrorRecord(
            session_id="session-1",
            computer="local",
            agent="claude",
            project="demo",
            title="Mirror title",
            timestamp_start="2025-01-15T11:55:00+00:00",
            timestamp_end="2025-01-15T12:05:00+00:00",
            conversation_text="old mirror text",
            message_count=2,
            metadata={"transcript_path": "/tmp/session.jsonl", "agent": "claude"},
            created_at="2025-01-15T12:05:00+00:00",
            updated_at="2025-01-15T12:05:00+00:00",
        )
        extracted_messages = [
            StructuredMessage(
                role="user",
                type="text",
                text="Please remember that I prefer short diffs.",
                timestamp="2025-01-15T12:01:00+00:00",
                entry_index=3,
            ),
            StructuredMessage(
                role="assistant",
                type="text",
                text="I will keep future diffs compact.",
                timestamp="2025-01-15T12:01:10+00:00",
                entry_index=4,
            ),
        ]
        captured_calls: list[tuple[str, str | None]] = []

        def fake_get_mirror(session_id: str) -> MirrorRecord | None:
            assert session_id == "session-1"
            return mirror

        def fake_extract_structured_messages(
            transcript_path: str,
            *args: object,
            since: str | None = None,
            **kwargs: object,
        ) -> list[StructuredMessage]:
            _ = args, kwargs
            captured_calls.append((transcript_path, since))
            return extracted_messages

        monkeypatch.setattr(job_module, "get_mirror", fake_get_mirror, raising=False)
        monkeypatch.setattr(job_module, "extract_structured_messages", fake_extract_structured_messages, raising=False)

        transcript_delta = await job._read_transcript_delta("session-1", since=since)

        assert transcript_delta == (
            "User: Please remember that I prefer short diffs.\n\nAssistant: I will keep future diffs compact."
        )
        assert captured_calls == [("/tmp/session.jsonl", "2025-01-15T12:00:00+00:00")]

    async def test_read_transcript_delta_returns_none_when_no_mirror_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        mirror_calls: list[str] = []
        extract_called = False

        def fake_get_mirror(session_id: str) -> MirrorRecord | None:
            mirror_calls.append(session_id)
            assert session_id == "session-404"
            return None

        def fake_extract_structured_messages(*args: object, **kwargs: object) -> list[StructuredMessage]:
            nonlocal extract_called
            _ = args, kwargs
            extract_called = True
            return []

        monkeypatch.setattr(job_module, "get_mirror", fake_get_mirror, raising=False)
        monkeypatch.setattr(job_module, "extract_structured_messages", fake_extract_structured_messages, raising=False)

        transcript_delta = await job._read_transcript_delta("session-404", since=None)

        assert transcript_delta is None
        assert mirror_calls == ["session-404"]
        assert extract_called is False

    async def test_read_transcript_delta_returns_none_when_boundary_has_no_new_messages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        since = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
        mirror = MirrorRecord(
            session_id="session-1",
            computer="local",
            agent="claude",
            project="demo",
            title="Mirror title",
            timestamp_start="2025-01-15T11:55:00+00:00",
            timestamp_end="2025-01-15T12:05:00+00:00",
            conversation_text="old mirror text",
            message_count=2,
            metadata={"transcript_path": "/tmp/session.jsonl", "agent": "claude"},
            created_at="2025-01-15T12:05:00+00:00",
            updated_at="2025-01-15T12:05:00+00:00",
        )
        mirror_calls: list[str] = []
        extract_calls: list[tuple[str, str | None]] = []

        def fake_get_mirror(session_id: str) -> MirrorRecord | None:
            mirror_calls.append(session_id)
            return mirror if session_id == "session-1" else None

        def fake_extract_structured_messages(
            transcript_path: str,
            *args: object,
            since: str | None = None,
            **kwargs: object,
        ) -> list[StructuredMessage]:
            _ = args, kwargs
            extract_calls.append((transcript_path, since))
            return []

        monkeypatch.setattr(job_module, "get_mirror", fake_get_mirror, raising=False)
        monkeypatch.setattr(job_module, "extract_structured_messages", fake_extract_structured_messages, raising=False)

        transcript_delta = await job._read_transcript_delta("session-1", since=since)

        assert transcript_delta is None
        assert mirror_calls == ["session-1"]
        assert extract_calls == [("/tmp/session.jsonl", "2025-01-15T12:00:00+00:00")]

    async def test_read_transcript_delta_returns_none_when_mirror_has_no_transcript_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        mirror = MirrorRecord(
            session_id="session-1",
            computer="local",
            agent="claude",
            project="demo",
            title="Mirror title",
            timestamp_start="2025-01-15T11:55:00+00:00",
            timestamp_end="2025-01-15T12:05:00+00:00",
            conversation_text="old mirror text",
            message_count=2,
            metadata={"agent": "claude"},
            created_at="2025-01-15T12:05:00+00:00",
            updated_at="2025-01-15T12:05:00+00:00",
        )
        extract_called = False

        def fake_get_mirror(session_id: str) -> MirrorRecord | None:
            assert session_id == "session-1"
            return mirror

        def fake_extract_structured_messages(*args: object, **kwargs: object) -> list[StructuredMessage]:
            nonlocal extract_called
            _ = args, kwargs
            extract_called = True
            return []

        monkeypatch.setattr(job_module, "get_mirror", fake_get_mirror, raising=False)
        monkeypatch.setattr(job_module, "extract_structured_messages", fake_extract_structured_messages, raising=False)

        transcript_delta = await job._read_transcript_delta("session-1", since=None)

        assert transcript_delta is None
        assert extract_called is False

    async def test_extract_personal_memories_persists_identity_scoped_observations_from_summarizer_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        session = _make_session(project_path="demo")
        captured_prompts: list[str] = []
        saved_inputs: list[object] = []

        async def fake_call_summarizer(
            prompt: str,
            schema: Mapping[str, object],
            parser: object,
        ) -> list[_MemoryCandidate]:
            _ = schema, parser
            captured_prompts.append(prompt)
            return [
                {
                    "type": "preference",
                    "title": "Prefers compact diffs",
                    "narrative": "Ada consistently asks for short diffs with minimal noise.",
                    "facts": ["Requests small diffs", "Values signal over commentary"],
                },
                {
                    "type": "context",
                    "title": "Comfortable with pytest",
                    "narrative": "Ada uses pytest heavily and expects strong regression coverage.",
                    "facts": ["Writes RED tests first"],
                },
            ]

        class FakeStore:
            async def save_observation(self, inp: object) -> object:
                saved_inputs.append(inp)
                return SimpleNamespace(id=len(saved_inputs), title="saved", project="demo")

        monkeypatch.setattr(job_module, "_call_summarizer", fake_call_summarizer, raising=False)
        monkeypatch.setattr(job_module, "MemoryStore", FakeStore, raising=False)

        await job._extract_personal_memories(
            "Ada prefers short diffs and expects strong pytest coverage.",
            None,
            session,
        )

        assert captured_prompts == []
        assert saved_inputs == []

        await job._extract_personal_memories(
            "Ada prefers short diffs and expects strong pytest coverage.",
            "person:ada",
            session,
        )

        assert captured_prompts
        assert "Ada prefers short diffs" in captured_prompts[0]
        assert len(saved_inputs) == 2
        first_input = saved_inputs[0]
        second_input = saved_inputs[1]
        assert first_input.project == "demo"
        assert first_input.identity_key == "person:ada"
        assert first_input.type is ObservationType.PREFERENCE
        assert first_input.title == "Prefers compact diffs"
        assert first_input.text == "Ada consistently asks for short diffs with minimal noise."
        assert first_input.facts == ["Requests small diffs", "Values signal over commentary"]
        assert second_input.project == "demo"
        assert second_input.identity_key == "person:ada"
        assert second_input.type is ObservationType.CONTEXT
        assert second_input.title == "Comfortable with pytest"
        assert second_input.text == "Ada uses pytest heavily and expects strong regression coverage."
        assert second_input.facts == ["Writes RED tests first"]

    async def test_extract_business_memories_persists_project_scoped_observations_without_identity_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        session = _make_session(project_path="demo")
        captured_prompts: list[str] = []
        saved_inputs: list[object] = []

        async def fake_call_summarizer(
            prompt: str,
            schema: Mapping[str, object],
            parser: object,
        ) -> list[_MemoryCandidate]:
            _ = schema, parser
            captured_prompts.append(prompt)
            return [
                {
                    "type": "discovery",
                    "title": "Search latency feedback",
                    "narrative": "Users report that search becomes noticeably slow after a refresh.",
                    "facts": ["Refresh amplifies latency", "Search is a recurring pain point"],
                },
                {
                    "type": "friction",
                    "title": "Release notes are hard to scan",
                    "narrative": "Customers struggle to extract relevant changes from long release notes.",
                    "facts": ["Needs concise summaries"],
                },
            ]

        class FakeStore:
            async def save_observation(self, inp: object) -> object:
                saved_inputs.append(inp)
                return SimpleNamespace(id=len(saved_inputs), title="saved", project="demo")

        monkeypatch.setattr(job_module, "_call_summarizer", fake_call_summarizer, raising=False)
        monkeypatch.setattr(job_module, "MemoryStore", FakeStore, raising=False)

        await job._extract_business_memories(
            "Search gets slow after refresh and long release notes are difficult to scan.",
            session,
        )

        assert captured_prompts
        assert "Search gets slow after refresh" in captured_prompts[0]
        assert len(saved_inputs) == 2
        first_input = saved_inputs[0]
        second_input = saved_inputs[1]
        assert first_input.project == "demo"
        assert first_input.identity_key is None
        assert first_input.type is ObservationType.DISCOVERY
        assert first_input.title == "Search latency feedback"
        assert first_input.text == "Users report that search becomes noticeably slow after a refresh."
        assert first_input.facts == ["Refresh amplifies latency", "Search is a recurring pain point"]
        assert second_input.project == "demo"
        assert second_input.identity_key is None
        assert second_input.type is ObservationType.FRICTION
        assert second_input.title == "Release notes are hard to scan"
        assert second_input.text == "Customers struggle to extract relevant changes from long release notes."
        assert second_input.facts == ["Needs concise summaries"]

    async def test_extract_personal_memories_noops_when_model_returns_no_memories(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        session = _make_session(project_path="demo")
        save_observation = AsyncMock()

        async def fake_call_summarizer(
            prompt: str,
            schema: Mapping[str, object],
            parser: object,
        ) -> list[_MemoryCandidate]:
            _ = prompt, schema, parser
            return []

        class FakeStore:
            async def save_observation(self, inp: object) -> object:
                return await save_observation(inp)

        monkeypatch.setattr(job_module, "_call_summarizer", fake_call_summarizer, raising=False)
        monkeypatch.setattr(job_module, "MemoryStore", FakeStore, raising=False)

        await job._extract_personal_memories("No durable memories here.", "person:ada", session)

        save_observation.assert_not_awaited()

    async def test_extract_business_memories_noops_when_model_returns_no_memories(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        session = _make_session(project_path="demo")
        save_observation = AsyncMock()

        async def fake_call_summarizer(
            prompt: str,
            schema: Mapping[str, object],
            parser: object,
        ) -> list[_MemoryCandidate]:
            _ = prompt, schema, parser
            return []

        class FakeStore:
            async def save_observation(self, inp: object) -> object:
                return await save_observation(inp)

        monkeypatch.setattr(job_module, "_call_summarizer", fake_call_summarizer, raising=False)
        monkeypatch.setattr(job_module, "MemoryStore", FakeStore, raising=False)

        await job._extract_business_memories("No durable business memories here.", session)

        save_observation.assert_not_awaited()

    async def test_extract_actionable_items_publishes_each_item_to_the_project_channel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        session = _make_session(session_id="session-9", project_path="demo")
        captured_prompts: list[str] = []
        channels_publisher = _FakeChannelsPublisher()
        redis_client = object()
        get_redis = AsyncMock(return_value=redis_client)

        async def fake_call_summarizer(
            prompt: str,
            schema: Mapping[str, object],
            parser: object,
        ) -> list[_ActionableItem]:
            _ = schema, parser
            captured_prompts.append(prompt)
            return [
                {"type": "bug", "summary": "Search hangs after refresh"},
                {"type": "feature-request", "summary": "Add saved search presets"},
                {"type": "follow-up", "summary": "Send the migration checklist to the user"},
            ]

        monkeypatch.setattr(job_module, "_call_summarizer", fake_call_summarizer, raising=False)
        monkeypatch.setattr(job_module, "get_redis", get_redis, raising=False)
        monkeypatch.setattr(job_module, "channels_publisher", channels_publisher, raising=False)

        await job._extract_and_publish_actionable_items(
            "Search hangs after refresh. We should add saved search presets and send a migration checklist.",
            session,
        )

        assert captured_prompts
        assert "Search hangs after refresh" in captured_prompts[0]
        get_redis.assert_awaited_once_with()
        assert len(channels_publisher.published_messages) == 3
        for published_message in channels_publisher.published_messages:
            assert published_message.redis is redis_client
            assert published_message.channel == "channel:demo:actionable-items"
            assert published_message.payload["session_id"] == "session-9"
        assert channels_publisher.published_messages[0].payload["type"] == "bug"
        assert channels_publisher.published_messages[0].payload["summary"] == "Search hangs after refresh"
        assert channels_publisher.published_messages[1].payload["type"] == "feature-request"
        assert channels_publisher.published_messages[1].payload["summary"] == "Add saved search presets"
        assert channels_publisher.published_messages[2].payload["type"] == "follow-up"
        assert channels_publisher.published_messages[2].payload["summary"] == "Send the migration checklist to the user"

    async def test_extract_actionable_items_noops_when_model_returns_no_items(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        session = _make_session(session_id="session-9", project_path="demo")
        channels_publisher = _FakeChannelsPublisher()
        get_redis = AsyncMock()

        async def fake_call_summarizer(
            prompt: str,
            schema: Mapping[str, object],
            parser: object,
        ) -> list[_ActionableItem]:
            _ = prompt, schema, parser
            return []

        monkeypatch.setattr(job_module, "_call_summarizer", fake_call_summarizer, raising=False)
        monkeypatch.setattr(job_module, "get_redis", get_redis, raising=False)
        monkeypatch.setattr(job_module, "channels_publisher", channels_publisher, raising=False)

        await job._extract_and_publish_actionable_items("Nothing actionable.", session)

        get_redis.assert_not_awaited()
        assert channels_publisher.published_messages == []

    async def test_extract_actionable_items_skips_when_redis_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        job = SessionMemoryExtractionJob()
        session = _make_session(session_id="session-9", project_path="demo")
        channels_publisher = _FakeChannelsPublisher()
        get_redis = AsyncMock(side_effect=RuntimeError("redis disabled"))
        warning_mock = Mock()

        async def fake_call_summarizer(
            prompt: str,
            schema: Mapping[str, object],
            parser: object,
        ) -> list[_ActionableItem]:
            _ = prompt, schema, parser
            return [{"type": "bug", "summary": "Search hangs after refresh"}]

        monkeypatch.setattr(job_module, "_call_summarizer", fake_call_summarizer, raising=False)
        monkeypatch.setattr(job_module, "get_redis", get_redis, raising=False)
        monkeypatch.setattr(job_module, "channels_publisher", channels_publisher, raising=False)
        monkeypatch.setattr(job_module.logger, "warning", warning_mock)

        await job._extract_and_publish_actionable_items("Search hangs after refresh.", session)

        get_redis.assert_awaited_once_with()
        assert channels_publisher.published_messages == []
        assert warning_mock.call_count == 1

    async def test_extract_actionable_items_logs_and_skips_transport_failures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = SessionMemoryExtractionJob()
        session = _make_session(session_id="session-9", project_path="demo")
        redis_client = object()
        get_redis = AsyncMock(return_value=redis_client)
        warning_mock = Mock()
        publish = AsyncMock(side_effect=[RuntimeError("boom"), RuntimeError("boom-again")])
        channels_publisher = SimpleNamespace(
            channel_key=lambda project, topic: f"channel:{project}:{topic}",
            publish=publish,
        )

        async def fake_call_summarizer(
            prompt: str,
            schema: Mapping[str, object],
            parser: object,
        ) -> list[_ActionableItem]:
            _ = prompt, schema, parser
            return [
                {"type": "bug", "summary": "Search hangs after refresh"},
                {"type": "follow-up", "summary": "Send the migration checklist"},
            ]

        monkeypatch.setattr(job_module, "_call_summarizer", fake_call_summarizer, raising=False)
        monkeypatch.setattr(job_module, "get_redis", get_redis, raising=False)
        monkeypatch.setattr(job_module, "channels_publisher", channels_publisher, raising=False)
        monkeypatch.setattr(job_module.logger, "warning", warning_mock)

        await job._extract_and_publish_actionable_items("Search hangs after refresh.", session)

        get_redis.assert_awaited_once_with()
        assert publish.await_count == 2
        assert warning_mock.call_count == 2

    async def test_process_session_skips_personal_extraction_when_identity_key_is_missing(self) -> None:
        job = _SpyProcessSessionJob(transcript="User: keep this preference", identity_key=None)
        session = _make_session(
            session_id="session-8",
            project_path="demo",
            last_memory_extraction_at=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
        )

        await job._process_session(session)

        assert job.personal_calls == []
        assert job.business_calls == [("User: keep this preference", session)]
        assert job.actionable_calls == [("User: keep this preference", session)]
        assert len(job.bookkeeping_calls) == 1
        assert job.bookkeeping_calls[0][0] == "session-8"

    async def test_process_session_returns_early_when_delta_is_empty(self) -> None:
        job = _SpyProcessSessionJob(transcript="   ", identity_key="person:ada")
        session = _make_session(
            session_id="session-6",
            project_path="demo",
            last_memory_extraction_at=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
        )

        await job._process_session(session)

        assert job.read_calls == [("session-6", datetime(2025, 1, 15, 12, 0, tzinfo=UTC))]
        assert job.personal_calls == []
        assert job.business_calls == []
        assert job.actionable_calls == []
        assert job.bookkeeping_calls == []

    async def test_process_session_updates_bookkeeping_without_injecting_compact_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        send_keys_existing_tmux = AsyncMock(return_value=True)

        monkeypatch.setattr(tmux_bridge_module, "send_keys_existing_tmux", send_keys_existing_tmux)

        idle_job = _SpyProcessSessionJob(transcript="", identity_key="person:ada")
        idle_session = _make_session(
            session_id="session-6",
            project_path="demo",
            last_memory_extraction_at=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
            tmux_session_name="tmux-session-6",
        )

        await idle_job._process_session(idle_session)

        assert idle_job.read_calls == [("session-6", datetime(2025, 1, 15, 12, 0, tzinfo=UTC))]
        assert idle_job.personal_calls == []
        assert idle_job.business_calls == []
        assert idle_job.actionable_calls == []
        assert idle_job.bookkeeping_calls == []
        send_keys_existing_tmux.assert_not_awaited()

        job = _SpyProcessSessionJob(transcript="User: keep this preference", identity_key="person:ada")
        session = _make_session(
            session_id="session-7",
            project_path="demo",
            last_memory_extraction_at=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
            tmux_session_name="tmux-session-7",
        )

        await job._process_session(session)

        assert job.read_calls == [("session-7", datetime(2025, 1, 15, 12, 0, tzinfo=UTC))]
        assert job.personal_calls == [("User: keep this preference", "person:ada", session)]
        assert job.business_calls == [("User: keep this preference", session)]
        assert job.actionable_calls == [("User: keep this preference", session)]
        assert len(job.bookkeeping_calls) == 1
        assert job.bookkeeping_calls[0][0] == "session-7"
        send_keys_existing_tmux.assert_not_awaited()

    async def test_process_session_updates_bookkeeping_only_after_success(self) -> None:
        job = _SpyProcessSessionJob(transcript="User: keep this preference", identity_key="person:ada")
        session = _make_session(
            session_id="session-10",
            project_path="demo",
            last_memory_extraction_at=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
        )
        failing_business = AsyncMock(side_effect=RuntimeError("boom"))
        bookkeeping = AsyncMock()
        job._extract_business_memories = failing_business
        job._update_bookkeeping = bookkeeping

        with pytest.raises(RuntimeError, match="boom"):
            await job._process_session(session)

        failing_business.assert_awaited_once_with("User: keep this preference", session)
        bookkeeping.assert_not_awaited()

    async def test_process_session_uses_last_memory_extraction_at_as_delta_boundary(self) -> None:
        job = _SpyProcessSessionJob(transcript="User: keep this preference", identity_key="person:ada")
        session = _make_session(
            session_id="session-11",
            project_path="demo",
            help_desk_processed_at=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
            last_memory_extraction_at=datetime(2025, 1, 15, 13, 0, tzinfo=UTC),
        )

        await job._process_session(session)

        assert job.read_calls == [("session-11", datetime(2025, 1, 15, 13, 0, tzinfo=UTC))]

    async def test_run_async_continues_after_per_session_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        job = SessionMemoryExtractionJob()
        sessions = [
            _make_session(session_id="session-ok", project_path="demo"),
            _make_session(session_id="session-bad", project_path="demo"),
        ]
        find_sessions = AsyncMock(return_value=sessions)
        process_session = AsyncMock(side_effect=[None, RuntimeError("boom")])

        monkeypatch.setattr(job, "_find_sessions_needing_extraction", find_sessions)
        monkeypatch.setattr(job, "_process_session", process_session)

        result = await job._run_async()

        find_sessions.assert_awaited_once_with()
        assert process_session.await_count == 2
        assert result.success is False
        assert result.items_processed == 1
        assert result.errors is not None
        assert len(result.errors) == 1
        assert "session-bad" in result.errors[0]
