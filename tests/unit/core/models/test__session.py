"""Characterization tests for teleclaude.core.models._session."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teleclaude.core.models._session import (
    Recording,
    Session,
    SessionLaunchIntent,
    SessionLaunchKind,
)


class TestSessionLaunchIntent:
    @pytest.mark.unit
    def test_to_dict_includes_kind_value(self):
        intent = SessionLaunchIntent(kind=SessionLaunchKind.AGENT, agent="claude")
        d = intent.to_dict()
        assert d["kind"] == "agent"
        assert d["agent"] == "claude"

    @pytest.mark.unit
    def test_to_dict_none_fields_present_as_none(self):
        intent = SessionLaunchIntent(kind=SessionLaunchKind.EMPTY)
        d = intent.to_dict()
        assert d["agent"] is None
        assert d["message"] is None
        assert d["thinking_mode"] is None
        assert d["native_session_id"] is None

    @pytest.mark.unit
    def test_from_dict_creates_correct_kind(self):
        intent = SessionLaunchIntent.from_dict({"kind": "agent", "agent": "codex"})
        assert intent.kind == SessionLaunchKind.AGENT
        assert intent.agent == "codex"

    @pytest.mark.unit
    def test_from_dict_missing_kind_raises_value_error(self):
        with pytest.raises(ValueError):
            SessionLaunchIntent.from_dict({"agent": "claude"})

    @pytest.mark.unit
    def test_from_dict_none_kind_raises_value_error(self):
        with pytest.raises(ValueError):
            SessionLaunchIntent.from_dict({"kind": None})

    @pytest.mark.unit
    def test_roundtrip(self):
        original = SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            agent="claude",
            thinking_mode="slow",
            message="hello",
            native_session_id="native-1",
        )
        restored = SessionLaunchIntent.from_dict(original.to_dict())
        assert restored.kind == original.kind
        assert restored.agent == original.agent
        assert restored.thinking_mode == original.thinking_mode
        assert restored.message == original.message
        assert restored.native_session_id == original.native_session_id


class TestSession:
    def _make_session(self, **kwargs: object) -> Session:
        defaults: dict[str, object] = {  # guard: loose-dict - Session constructor kwargs for test helpers
            "session_id": "s1",
            "computer_name": "local",
            "tmux_session_name": "tc-s1",
            "title": "Test Session",
        }
        defaults.update(kwargs)
        return Session(**defaults)

    @pytest.mark.unit
    def test_get_origin_section_returns_dict(self):
        session = self._make_session(origin_metadata={"telegram": {"topic_id": 7}})
        assert session.get_origin_section("telegram") == {"topic_id": 7}
        assert session.get_origin_section("missing") == {}

    @pytest.mark.unit
    def test_to_dict_serializes_datetime_as_iso_string(self):
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        session = self._make_session(created_at=now, last_agent_stop_at=now)
        d = session.to_dict()
        assert d["created_at"] == now.isoformat()
        assert d["last_agent_stop_at"] == now.isoformat()

    @pytest.mark.unit
    def test_to_dict_origin_metadata_included(self):
        session = self._make_session(origin_metadata={"telegram": {"topic_id": 7}})
        d = session.to_dict()
        assert d["origin_metadata"] == {"telegram": {"topic_id": 7}}

    @pytest.mark.unit
    def test_to_dict_system_role_and_job_included(self):
        session = self._make_session(system_role="worker", job="builder")
        d = session.to_dict()
        assert d["system_role"] == "worker"
        assert d["job"] == "builder"

    @pytest.mark.unit
    def test_from_dict_restores_basic_fields(self):
        data = {
            "session_id": "s99",
            "computer_name": "box1",
            "tmux_session_name": "tc-s99",
            "title": "My Session",
        }
        session = Session.from_dict(data)
        assert session.session_id == "s99"
        assert session.computer_name == "box1"
        assert session.title == "My Session"

    @pytest.mark.unit
    def test_from_dict_origin_metadata_parsed(self):
        data = {
            "session_id": "s1",
            "computer_name": "x",
            "tmux_session_name": "t-s1",
            "title": "T",
            "origin_metadata": {"telegram": {"topic_id": 77}},
        }
        session = Session.from_dict(data)
        assert session.get_origin_section("telegram")["topic_id"] == 77

    @pytest.mark.unit
    def test_from_dict_missing_origin_metadata_uses_empty(self):
        data = {
            "session_id": "s1",
            "computer_name": "x",
            "tmux_session_name": "t-s1",
            "title": "T",
        }
        session = Session.from_dict(data)
        assert session.origin_metadata == {}

    @pytest.mark.unit
    def test_from_dict_system_role_and_job_parsed(self):
        data = {
            "session_id": "s1",
            "computer_name": "local",
            "tmux_session_name": "tc-s1",
            "title": "T",
            "system_role": "agent",
            "job": "reviewer",
        }
        session = Session.from_dict(data)
        assert session.system_role == "agent"
        assert session.job == "reviewer"

    @pytest.mark.unit
    def test_from_dict_human_role_defaults_to_none_when_missing(self):
        data = {
            "session_id": "s1",
            "computer_name": "local",
            "tmux_session_name": "tc-s1",
            "title": "T",
        }
        session = Session.from_dict(data)
        assert session.human_role is None

    @pytest.mark.unit
    def test_from_dict_lifecycle_status_defaults_to_active_when_missing(self):
        data = {
            "session_id": "s1",
            "computer_name": "local",
            "tmux_session_name": "tc-s1",
            "title": "T",
        }
        session = Session.from_dict(data)
        assert session.lifecycle_status == "active"

    @pytest.mark.unit
    def test_from_dict_restores_last_agent_stop_at(self):
        stop_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        data = {
            "session_id": "s1",
            "computer_name": "local",
            "tmux_session_name": "tc-s1",
            "title": "T",
            "last_agent_stop_at": stop_at.isoformat(),
        }
        session = Session.from_dict(data)
        assert session.last_agent_stop_at == stop_at

    @pytest.mark.unit
    def test_last_projected_at_defaults_to_none(self):
        session = self._make_session()
        assert session.last_projected_at is None

    @pytest.mark.unit
    def test_to_dict_serializes_last_projected_at(self):
        ts = datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC)
        session = self._make_session(last_projected_at=ts)
        d = session.to_dict()
        assert d["last_projected_at"] == ts.isoformat()

    @pytest.mark.unit
    def test_from_dict_restores_last_projected_at(self):
        ts = datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC)
        data = {
            "session_id": "s1",
            "computer_name": "local",
            "tmux_session_name": "tc-s1",
            "title": "T",
            "last_projected_at": ts.isoformat(),
        }
        session = Session.from_dict(data)
        assert session.last_projected_at == ts


class TestRecording:
    @pytest.mark.unit
    def test_to_dict_serializes_timestamp_as_iso(self):
        ts = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
        rec = Recording(recording_id=1, session_id="s1", file_path="/f", recording_type="output", timestamp=ts)
        d = rec.to_dict()
        assert d["timestamp"] == ts.isoformat()

    @pytest.mark.unit
    def test_to_dict_no_timestamp(self):
        rec = Recording(recording_id=None, session_id="s1", file_path="/f", recording_type="output")
        d = rec.to_dict()
        assert d.get("timestamp") is None

    @pytest.mark.unit
    def test_from_dict_restores_fields(self):
        ts = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
        data = {
            "recording_id": 42,
            "session_id": "s1",
            "file_path": "/recordings/f.txt",
            "recording_type": "output",
            "timestamp": ts.isoformat(),
        }
        rec = Recording.from_dict(data)
        assert rec.recording_id == 42
        assert rec.session_id == "s1"
        assert rec.file_path == "/recordings/f.txt"
        assert rec.recording_type == "output"
        assert rec.timestamp is not None

    @pytest.mark.unit
    def test_from_dict_none_timestamp_yields_none(self):
        data = {
            "recording_id": 1,
            "session_id": "s1",
            "file_path": "/f",
            "recording_type": "output",
            "timestamp": None,
        }
        rec = Recording.from_dict(data)
        assert rec.timestamp is None
