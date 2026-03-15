"""Characterization tests for teleclaude.core.command_handlers._session."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.command_handlers import _session
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import (
    ProjectInfo,
    Session,
    SessionLaunchIntent,
    SessionLaunchKind,
    SessionMetadata,
    TodoInfo,
)
from teleclaude.types.commands import CloseSessionCommand, CreateSessionCommand, GetSessionDataCommand


def make_session(
    *,
    session_id: str = "sess-001",
    tmux_session_name: str = "tc-sess-001",
    lifecycle_status: str = "active",
    title: str = "Session",
    project_path: str | None = "/tmp/project",
    subdir: str | None = None,
    thinking_mode: str | None = None,
    active_agent: str | None = "claude",
    native_log_file: str | None = None,
    last_output_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> Session:
    """Build a concrete session for session-handler tests."""
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=tmux_session_name,
        title=title,
        lifecycle_status=lifecycle_status,
        project_path=project_path,
        subdir=subdir,
        thinking_mode=thinking_mode,
        active_agent=active_agent,
        native_log_file=native_log_file,
        last_output_at=last_output_at,
        closed_at=closed_at,
    )


class TestCreateSession:
    @pytest.mark.unit
    async def test_restricted_sessions_are_jailed_to_help_desk(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_path = tmp_path / "project"
        project_path.mkdir()
        help_desk = tmp_path / "help-desk"

        config = SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir=str(help_desk)))
        db = SimpleNamespace(
            create_session=AsyncMock(return_value=make_session()),
            update_session=AsyncMock(),
            get_session=AsyncMock(return_value=None),
        )
        identity_resolver = SimpleNamespace(
            resolve=lambda _origin, _metadata: SimpleNamespace(
                person_email=None,
                person_role=None,
                platform=None,
                platform_user_id=None,
            )
        )

        monkeypatch.setattr(_session, "config", config)
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "get_identity_resolver", lambda: identity_resolver)

        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="telegram",
            subdir="feature-branch",
            working_slug="feature-x",
            session_metadata=SessionMetadata(human_role="member"),
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                agent="claude",
                thinking_mode="slow",
            ),
        )

        result = await _session.create_session(cmd, SimpleNamespace())

        create_call = db.create_session.await_args
        assert create_call.kwargs["project_path"] == str(help_desk)
        assert create_call.kwargs["subdir"] is None
        assert create_call.kwargs["working_slug"] is None
        assert create_call.kwargs["lifecycle_status"] == "initializing"
        assert result["tmux_session_name"].startswith(_session.TMUX_SESSION_PREFIX)


class TestSessionListing:
    @pytest.mark.unit
    async def test_list_sessions_builds_snapshots_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(lifecycle_status="", thinking_mode=None)
        session.last_message_sent = "ping"
        db = SimpleNamespace(list_sessions=AsyncMock(return_value=[session]))
        config = SimpleNamespace(computer=SimpleNamespace(name="local"))

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "config", config)
        monkeypatch.setattr(_session, "get_last_output_summary", MagicMock(return_value="summary"))

        result = await _session.list_sessions()

        assert len(result) == 1
        assert result[0].thinking_mode == "slow"
        assert result[0].status == "active"
        assert result[0].computer == "local"
        assert result[0].last_output_summary == "summary"

    @pytest.mark.unit
    async def test_list_projects_filters_missing_directories(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        existing = tmp_path / "existing"
        existing.mkdir()
        missing = tmp_path / "missing"
        config = SimpleNamespace(
            computer=SimpleNamespace(
                get_all_trusted_dirs=lambda: [
                    SimpleNamespace(name="Existing", desc="Primary", path=str(existing)),
                    SimpleNamespace(name="Missing", desc="Gone", path=str(missing)),
                ]
            )
        )

        monkeypatch.setattr(_session, "config", config)

        result = await _session.list_projects()

        assert [(project.name, project.path) for project in result] == [("Existing", str(existing))]

    @pytest.mark.unit
    async def test_list_projects_with_todos_attaches_project_todos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        project = ProjectInfo(name="Existing", path="/tmp/project")
        todo = TodoInfo(slug="todo-1", status="pending")

        monkeypatch.setattr(_session, "list_projects", AsyncMock(return_value=[project]))
        monkeypatch.setattr(_session, "list_todos", AsyncMock(return_value=[todo]))

        result = await _session.list_projects_with_todos()

        assert len(result) == 1
        assert [item.slug for item in result[0].todos] == ["todo-1"]


class TestComputerInfo:
    @pytest.mark.unit
    async def test_get_computer_info_returns_rounded_system_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = SimpleNamespace(
            computer=SimpleNamespace(
                name="local",
                user="dev",
                role="builder",
                host="localhost",
                tmux_binary="/usr/bin/tmux",
            )
        )
        psutil = SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(
                total=16 * 1024**3,
                available=4 * 1024**3,
                percent=75.0,
            ),
            disk_usage=lambda _path: SimpleNamespace(
                total=200 * 1024**3,
                free=50 * 1024**3,
                percent=75.0,
            ),
            cpu_percent=lambda _interval: 12.5,
        )

        monkeypatch.setattr(_session, "config", config)
        monkeypatch.setattr(_session, "psutil", psutil)

        info = await _session.get_computer_info()

        assert info.name == "local"
        assert info.tmux_binary == "/usr/bin/tmux"
        assert info.system_stats is not None
        assert info.system_stats["memory"]["total_gb"] == 16.0
        assert info.system_stats["disk"]["free_gb"] == 50.0
        assert info.system_stats["cpu"]["percent_used"] == 12.5


class TestGetSessionData:
    @pytest.mark.unit
    async def test_missing_session_returns_error_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_session, "db", SimpleNamespace(get_session=AsyncMock(return_value=None)))

        result = await _session.get_session_data(GetSessionDataCommand(session_id="missing"))

        assert result["status"] == "error"
        assert isinstance(result["error"], str)
        assert result["error"] != ""

    @pytest.mark.unit
    async def test_missing_native_log_uses_tmux_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(native_log_file=None, last_output_at=None)
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        tmux_bridge = SimpleNamespace(capture_pane=AsyncMock(return_value="\x1b[31mhello world\x1b[0m"))

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "tmux_bridge", tmux_bridge)

        result = await _session.get_session_data(GetSessionDataCommand(session_id=session.session_id, tail_chars=5))

        assert result["status"] == "success"
        assert result["messages"] == "world"
        assert "\x1b" not in result["messages"]

    @pytest.mark.unit
    async def test_existing_native_log_is_parsed_to_messages(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        transcript_path = tmp_path / "session.jsonl"
        transcript_path.write_text("{}", encoding="utf-8")
        session = make_session(native_log_file=str(transcript_path))
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(
            _session, "get_transcript_parser_info", MagicMock(return_value=SimpleNamespace(display_name="Claude"))
        )
        monkeypatch.setattr(_session, "parse_session_transcript", MagicMock(return_value="# transcript"))

        result = await _session.get_session_data(GetSessionDataCommand(session_id=session.session_id, tail_chars=200))

        assert result["status"] == "success"
        assert result["messages"] == "# transcript"


class TestEndSession:
    @pytest.mark.unit
    async def test_closed_session_replays_session_closed_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(closed_at=datetime.now(UTC))
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        event_bus = SimpleNamespace(emit=MagicMock())
        terminate_session = AsyncMock(return_value=True)

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "event_bus", event_bus)
        monkeypatch.setattr(_session, "terminate_session", terminate_session)

        result = await _session.end_session(CloseSessionCommand(session_id=session.session_id), SimpleNamespace())

        assert result["status"] == "success"
        event_bus.emit.assert_called_once()
        assert event_bus.emit.call_args.args[0] == TeleClaudeEvents.SESSION_CLOSED
        terminate_session.assert_not_awaited()
