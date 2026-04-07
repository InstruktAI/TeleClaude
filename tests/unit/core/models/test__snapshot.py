"""Characterization tests for teleclaude.core.models._snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from teleclaude.api_models import TodoDTO
from teleclaude.core.models._session import Session
from teleclaude.core.models._snapshot import (
    ComputerInfo,
    ProjectInfo,
    SessionSnapshot,
)


class TestSessionSnapshot:
    def _make_session(self, **kwargs: object) -> Session:
        defaults: dict[str, object] = {  # guard: loose-dict - Session constructor kwargs for test helpers
            "session_id": "snap-1",
            "computer_name": "local",
            "tmux_session_name": "tc-snap-1",
            "title": "Snap Session",
        }
        defaults.update(kwargs)
        return Session(**defaults)

    @pytest.mark.unit
    def test_to_dict_contains_required_keys(self):
        snap = SessionSnapshot(
            session_id="s1",
            last_input_origin=None,
            title="T",
            thinking_mode=None,
            active_agent=None,
            status="active",
        )
        d = snap.to_dict()
        assert "session_id" in d
        assert "title" in d
        assert "status" in d
        assert "visibility" in d

    @pytest.mark.unit
    def test_to_dict_system_role_and_job_serialized(self):
        snap = SessionSnapshot(
            session_id="s1",
            last_input_origin=None,
            title="T",
            thinking_mode=None,
            active_agent=None,
            status="active",
            system_role="worker",
            job="builder",
        )
        d = snap.to_dict()
        assert d["system_role"] == "worker"
        assert d["job"] == "builder"

    @pytest.mark.unit
    def test_to_dict_no_system_role_is_none(self):
        snap = SessionSnapshot(
            session_id="s1",
            last_input_origin=None,
            title="T",
            thinking_mode=None,
            active_agent=None,
            status="active",
        )
        d = snap.to_dict()
        assert d["system_role"] is None
        assert d["job"] is None

    @pytest.mark.unit
    def test_from_db_session_copies_basic_fields(self):
        now = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)
        session = self._make_session(
            project_path="/myproject",
            thinking_mode="slow",
            active_agent="claude",
            lifecycle_status="active",
            created_at=now,
        )
        snap = SessionSnapshot.from_db_session(session, computer="box1")
        assert snap.session_id == "snap-1"
        assert snap.title == "Snap Session"
        assert snap.project_path == "/myproject"
        assert snap.thinking_mode == "slow"
        assert snap.active_agent == "claude"
        assert snap.status == "active"
        assert snap.computer == "box1"
        assert snap.created_at == now.isoformat()

    @pytest.mark.unit
    def test_from_db_session_visibility_defaults_to_private_when_none(self):
        session = self._make_session(visibility=None)
        snap = SessionSnapshot.from_db_session(session)
        assert snap.visibility == "private"

    @pytest.mark.unit
    def test_from_db_session_last_output_summary_from_feedback(self):
        session = self._make_session(last_output_summary="summary text", last_output_raw="raw")
        with patch("teleclaude.core.models._snapshot.get_last_output_summary", return_value="summary text") as mock_fn:
            snap = SessionSnapshot.from_db_session(session)
            mock_fn.assert_called_once_with(session)
        assert snap.last_output_summary == "summary text"

    @pytest.mark.unit
    def test_from_db_session_sets_idle_agent_status_when_stop_matches_last_activity(self):
        input_at = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
        stop_at = datetime(2025, 2, 1, 12, 0, 5, tzinfo=UTC)
        session = self._make_session(last_message_sent_at=input_at, last_activity=stop_at, last_agent_stop_at=stop_at)
        snap = SessionSnapshot.from_db_session(session)
        assert snap.last_input_at == input_at.isoformat()
        assert snap.last_agent_stop_at == stop_at.isoformat()
        assert snap.agent_status == "idle"

    @pytest.mark.unit
    def test_from_db_session_sets_active_agent_status_when_activity_exists_after_stop(self):
        input_at = datetime(2025, 2, 1, 12, 0, 5, tzinfo=UTC)
        activity_at = datetime(2025, 2, 1, 12, 0, 6, tzinfo=UTC)
        stop_at = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
        session = self._make_session(
            last_message_sent_at=input_at, last_activity=activity_at, last_agent_stop_at=stop_at
        )
        snap = SessionSnapshot.from_db_session(session)
        assert snap.agent_status == "active"

    @pytest.mark.unit
    def test_from_db_session_sets_active_agent_status_when_stop_is_missing(self):
        activity_at = datetime(2025, 2, 1, 12, 0, 6, tzinfo=UTC)
        session = self._make_session(last_activity=activity_at, last_agent_stop_at=None)
        snap = SessionSnapshot.from_db_session(session)
        assert snap.agent_status == "active"

    @pytest.mark.unit
    def test_from_dict_restores_fields(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "session_id": "s10",
            "title": "Test",
            "status": "active",
            "thinking_mode": "fast",
            "active_agent": "claude",
            "last_input_origin": "telegram",
        }
        snap = SessionSnapshot.from_dict(data)
        assert snap.session_id == "s10"
        assert snap.title == "Test"
        assert snap.thinking_mode == "fast"
        assert snap.last_input_origin == "telegram"

    @pytest.mark.unit
    def test_from_dict_last_output_summary_falls_back_to_last_output(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "session_id": "s1",
            "title": "T",
            "status": "active",
            "thinking_mode": None,
            "active_agent": None,
            "last_input_origin": None,
            "last_output": "legacy output",
        }
        snap = SessionSnapshot.from_dict(data)
        assert snap.last_output_summary == "legacy output"

    @pytest.mark.unit
    def test_from_dict_visibility_defaults_to_private_when_absent(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "session_id": "s1",
            "title": "T",
            "status": "active",
            "thinking_mode": None,
            "active_agent": None,
            "last_input_origin": None,
        }
        snap = SessionSnapshot.from_dict(data)
        assert snap.visibility == "private"

    @pytest.mark.unit
    def test_from_dict_system_role_and_job_parsed(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "session_id": "s1",
            "title": "T",
            "status": "active",
            "thinking_mode": None,
            "active_agent": None,
            "last_input_origin": None,
            "system_role": "builder",
            "job": "build",
        }
        snap = SessionSnapshot.from_dict(data)
        assert snap.system_role == "builder"
        assert snap.job == "build"


class TestComputerInfo:
    @pytest.mark.unit
    def test_to_dict_returns_dict(self):
        info = ComputerInfo(name="box1", status="online")
        d = info.to_dict()
        assert isinstance(d, dict)
        assert d["name"] == "box1"
        assert d["status"] == "online"


class TestProjectInfo:
    @pytest.mark.unit
    def test_from_dict_with_todos(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "name": "proj",
            "path": "/proj",
            "todos": [{"slug": "t1", "status": "pending", "has_requirements": False, "has_impl_plan": False}],
        }
        info = ProjectInfo.from_dict(data)
        assert info.name == "proj"
        assert len(info.todos) == 1
        assert info.todos[0].slug == "t1"

    @pytest.mark.unit
    def test_from_dict_description_falls_back_to_desc(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "name": "proj",
            "path": "/proj",
            "desc": "Short desc",
        }
        info = ProjectInfo.from_dict(data)
        assert info.description == "Short desc"

    @pytest.mark.unit
    def test_to_dict_serializes_todos(self):
        info = ProjectInfo(
            name="p", path="/p", todos=[TodoDTO(slug="t1", status="done", has_requirements=False, has_impl_plan=False)]
        )
        d = info.to_dict()
        assert isinstance(d["todos"], list)
        assert d["todos"][0]["slug"] == "t1"  # type: ignore[index]
