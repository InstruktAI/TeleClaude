"""Characterization tests for teleclaude.core.models._snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from teleclaude.core.models._session import Session, SessionMetadata
from teleclaude.core.models._snapshot import (
    ComputerInfo,
    ProjectInfo,
    RunAgentCommandArgs,
    SessionSnapshot,
    StartSessionArgs,
    ThinkingMode,
    TodoInfo,
)


class TestThinkingMode:
    @pytest.mark.unit
    def test_enum_values(self):
        assert ThinkingMode.FAST.value == "fast"
        assert ThinkingMode.MED.value == "med"
        assert ThinkingMode.SLOW.value == "slow"
        assert ThinkingMode.DEEP.value == "deep"


class TestStartSessionArgs:
    @pytest.mark.unit
    def test_defaults(self):
        args = StartSessionArgs(computer="local", project_path="/p", title="T", message="m")
        assert args.agent == "claude"
        assert args.thinking_mode == ThinkingMode.SLOW
        assert args.caller_session_id is None
        assert args.direct is False

    @pytest.mark.unit
    def test_fields_set(self):
        args = StartSessionArgs(
            computer="remote",
            project_path="/proj",
            title="Demo",
            message="go",
            agent="codex",
            thinking_mode=ThinkingMode.FAST,
            caller_session_id="parent-1",
            direct=True,
        )
        assert args.computer == "remote"
        assert args.direct is True
        assert args.agent == "codex"


class TestRunAgentCommandArgs:
    @pytest.mark.unit
    def test_defaults(self):
        args = RunAgentCommandArgs(computer="local", command="/next-build")
        assert args.args == ""
        assert args.project is None
        assert args.agent == "claude"
        assert args.thinking_mode == ThinkingMode.SLOW
        assert args.subfolder == ""
        assert args.caller_session_id is None


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
    def test_to_dict_session_metadata_serialized_as_dict(self):
        sm = SessionMetadata(system_role="agent")
        snap = SessionSnapshot(
            session_id="s1",
            last_input_origin=None,
            title="T",
            thinking_mode=None,
            active_agent=None,
            status="active",
            session_metadata=sm,
        )
        d = snap.to_dict()
        assert isinstance(d["session_metadata"], dict)
        assert d["session_metadata"]["system_role"] == "agent"

    @pytest.mark.unit
    def test_to_dict_no_session_metadata_is_none(self):
        snap = SessionSnapshot(
            session_id="s1",
            last_input_origin=None,
            title="T",
            thinking_mode=None,
            active_agent=None,
            status="active",
        )
        d = snap.to_dict()
        assert d["session_metadata"] is None

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
    def test_from_dict_session_metadata_dict_parsed(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "session_id": "s1",
            "title": "T",
            "status": "active",
            "thinking_mode": None,
            "active_agent": None,
            "last_input_origin": None,
            "session_metadata": {"system_role": "builder", "job": "build"},
        }
        snap = SessionSnapshot.from_dict(data)
        assert snap.session_metadata is not None
        assert snap.session_metadata.system_role == "builder"


class TestComputerInfo:
    @pytest.mark.unit
    def test_to_dict_returns_dict(self):
        info = ComputerInfo(name="box1", status="online")
        d = info.to_dict()
        assert isinstance(d, dict)
        assert d["name"] == "box1"
        assert d["status"] == "online"

    @pytest.mark.unit
    def test_defaults(self):
        info = ComputerInfo(name="box1", status="online")
        assert info.user is None
        assert info.host is None
        assert info.role is None
        assert info.is_local is False
        assert info.system_stats is None
        assert info.tmux_binary is None


class TestTodoInfo:
    @pytest.mark.unit
    def test_from_dict_basic_fields(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "slug": "my-todo",
            "status": "in_progress",
        }
        info = TodoInfo.from_dict(data)
        assert info.slug == "my-todo"
        assert info.status == "in_progress"

    @pytest.mark.unit
    def test_from_dict_dor_score_converted_to_int(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "slug": "t",
            "status": "pending",
            "dor_score": "85",
        }
        info = TodoInfo.from_dict(data)
        assert info.dor_score == 85

    @pytest.mark.unit
    def test_from_dict_invalid_dor_score_becomes_none(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "slug": "t",
            "status": "pending",
            "dor_score": "invalid",
        }
        info = TodoInfo.from_dict(data)
        assert info.dor_score is None

    @pytest.mark.unit
    def test_from_dict_description_falls_back_to_title(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "slug": "t",
            "status": "pending",
            "title": "My Title",
        }
        info = TodoInfo.from_dict(data)
        assert info.description == "My Title"

    @pytest.mark.unit
    def test_from_dict_files_and_after_cast_to_str_list(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "slug": "t",
            "status": "pending",
            "files": [1, 2],
            "after": ["dep-1"],
        }
        info = TodoInfo.from_dict(data)
        assert info.files == ["1", "2"]
        assert info.after == ["dep-1"]

    @pytest.mark.unit
    def test_to_dict_roundtrip(self):
        info = TodoInfo(slug="my-todo", status="pending", description="desc", dor_score=90)
        d = info.to_dict()
        assert d["slug"] == "my-todo"
        assert d["dor_score"] == 90


class TestProjectInfo:
    @pytest.mark.unit
    def test_from_dict_with_todos(self):
        data: dict[str, object] = {  # guard: loose-dict - from_dict test input
            "name": "proj",
            "path": "/proj",
            "todos": [{"slug": "t1", "status": "pending"}],
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
        info = ProjectInfo(name="p", path="/p", todos=[TodoInfo(slug="t1", status="done")])
        d = info.to_dict()
        assert isinstance(d["todos"], list)
        assert d["todos"][0]["slug"] == "t1"  # type: ignore[index]
