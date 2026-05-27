"""Characterization tests for teleclaude.core.command_handlers._session."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.api_models import TodoDTO
from teleclaude.core.command_handlers import _session, _utils
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import (
    ProjectInfo,
    Session,
    SessionLaunchIntent,
    SessionLaunchKind,
    _snapshot,
)
from teleclaude.core.models._adapter import TerminalOriginMetadata
from teleclaude.types.commands import CloseSessionCommand, CreateSessionCommand, GetSessionDataCommand

_PARENT_ID = "parent-1"
_LOCAL = "local"
_LIFECYCLE_ACTIVE = "active"
_LIFECYCLE_HEADLESS = "headless"
_LIFECYCLE_INITIALIZING = "initializing"
_LIFECYCLE_CLOSING = "closing"
_LIFECYCLE_CLOSED = "closed"
_ROLE_CUSTOMER = "customer"
_THINKING_SLOW = "slow"
_OUTPUT_SUMMARY = "summary"
_TMUX_BINARY = "/usr/bin/tmux"
_HEADLESS_SESSION_ID = "headless-001"
_NATIVE_SESSION_ID = "native-123"
_NATIVE_LOG_PATH = "/tmp/native.log"
_EMPTY = ""
_STATUS_SUCCESS = "success"
_STATUS_ERROR = "error"
_MESSAGES_WORLD = "world"
_MESSAGES_TRANSCRIPT = "# transcript"
_PROJECT_EXISTING = "Existing"
_TODO_SLUG = "todo-1"


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
    async def test_skip_listener_registration_marks_session_detached(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_path = tmp_path / "project"
        project_path.mkdir()
        help_desk = tmp_path / "help-desk"

        parent_session = make_session(session_id="parent-1", tmux_session_name="tc-parent-1")
        db = SimpleNamespace(
            create_session=AsyncMock(return_value=make_session(session_id="child-1")),
            update_origin_metadata=AsyncMock(),
            get_session=AsyncMock(return_value=parent_session),
        )

        def _resolve(_origin: str, _metadata: object) -> SimpleNamespace:
            return SimpleNamespace(
                person_email="admin@example.com",
                person_role="admin",
                platform="terminal",
                platform_user_id="admin@example.com",
            )

        monkeypatch.setattr(
            _session,
            "config",
            SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir=str(help_desk))),
        )
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "get_identity_resolver", lambda: SimpleNamespace(resolve=_resolve))

        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="terminal",
            origin_metadata=TerminalOriginMetadata(email="admin@example.com"),
            initiator_session_id="parent-1",
            skip_listener_registration=True,
        )

        await _session.create_session(cmd, SimpleNamespace())

        create_call = db.create_session.await_args
        assert create_call.kwargs["initiator_session_id"] == _PARENT_ID
        assert create_call.kwargs["detached"] is True

    @pytest.mark.unit
    async def test_listener_registration_sessions_remain_attached(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_path = tmp_path / "project"
        project_path.mkdir()
        help_desk = tmp_path / "help-desk"

        parent_session = make_session(session_id="parent-1", tmux_session_name="tc-parent-1")
        db = SimpleNamespace(
            create_session=AsyncMock(return_value=make_session(session_id="child-2")),
            update_origin_metadata=AsyncMock(),
            get_session=AsyncMock(return_value=parent_session),
        )
        register_listener = AsyncMock()

        def _resolve(_origin: str, _metadata: object) -> SimpleNamespace:
            return SimpleNamespace(
                person_email="admin@example.com",
                person_role="admin",
                platform="terminal",
                platform_user_id="admin@example.com",
            )

        monkeypatch.setattr(
            _session,
            "config",
            SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir=str(help_desk))),
        )
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "register_listener", register_listener)
        monkeypatch.setattr(_session, "get_identity_resolver", lambda: SimpleNamespace(resolve=_resolve))

        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="terminal",
            origin_metadata=TerminalOriginMetadata(email="admin@example.com"),
            initiator_session_id="parent-1",
            skip_listener_registration=False,
        )

        await _session.create_session(cmd, SimpleNamespace())

        create_call = db.create_session.await_args
        assert create_call.kwargs["initiator_session_id"] == _PARENT_ID
        assert create_call.kwargs["detached"] is False
        register_listener.assert_awaited_once()

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
            update_origin_metadata=AsyncMock(),
            get_session=AsyncMock(return_value=None),
        )

        def _resolve(_origin: str, _metadata: object) -> SimpleNamespace:
            return SimpleNamespace(
                person_email=None,
                person_role="newcomer",
                platform=None,
                platform_user_id=None,
            )

        identity_resolver = SimpleNamespace(resolve=_resolve)

        monkeypatch.setattr(_session, "config", config)
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "get_identity_resolver", lambda: identity_resolver)

        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="telegram",
            subdir="feature-branch",
            origin_metadata={"user_id": 123, "platform": "telegram"},
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
        assert create_call.kwargs["lifecycle_status"] == _LIFECYCLE_INITIALIZING
        # A non-headless session was created (got a tmux name); headless would be empty.
        assert result["tmux_session_name"]

    @pytest.mark.unit
    async def test_headless_commands_create_headless_rows_without_tmux_name(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_path = tmp_path / "project"
        project_path.mkdir()
        help_desk = tmp_path / "help-desk"

        config = SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir=str(help_desk)))
        db = SimpleNamespace(
            create_session=AsyncMock(return_value=make_session(tmux_session_name="", lifecycle_status="headless")),
            update_origin_metadata=AsyncMock(),
            get_session=AsyncMock(return_value=None),
        )

        def _resolve(_origin: str, _metadata: object) -> SimpleNamespace:
            return SimpleNamespace(
                person_email="admin@example.com",
                person_role="admin",
                platform="terminal",
                platform_user_id="admin@example.com",
            )

        monkeypatch.setattr(_session, "config", config)
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "get_identity_resolver", lambda: SimpleNamespace(resolve=_resolve))

        cmd = CreateSessionCommand(
            session_id="headless-001",
            headless=True,
            native_session_id="native-123",
            native_log_file="/tmp/native.log",
            project_path=str(project_path),
            origin="terminal",
            origin_metadata={"email": "admin@example.com"},
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                agent="codex",
                native_session_id="native-123",
            ),
        )

        result = await _session.create_session(cmd, SimpleNamespace())

        create_call = db.create_session.await_args
        assert create_call.kwargs["session_id"] == _HEADLESS_SESSION_ID
        assert create_call.kwargs["tmux_session_name"] == _EMPTY
        assert create_call.kwargs["lifecycle_status"] == _LIFECYCLE_HEADLESS
        assert create_call.kwargs["native_session_id"] == _NATIVE_SESSION_ID
        assert create_call.kwargs["native_log_file"] == _NATIVE_LOG_PATH
        assert result["tmux_session_name"] == _EMPTY

    @pytest.mark.unit
    async def test_headless_terminal_customers_are_jailed_to_help_desk(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_path = tmp_path / "project"
        project_path.mkdir()
        help_desk = tmp_path / "help-desk"

        config = SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir=str(help_desk)))
        db = SimpleNamespace(
            create_session=AsyncMock(return_value=make_session(tmux_session_name="", lifecycle_status="headless")),
            update_origin_metadata=AsyncMock(),
            get_session=AsyncMock(return_value=None),
        )

        def _resolve(_origin: str, _metadata: object) -> SimpleNamespace:
            return SimpleNamespace(
                person_email="customer@example.com",
                person_role="customer",
                platform="terminal",
                platform_user_id="customer@example.com",
            )

        monkeypatch.setattr(_session, "config", config)
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "get_identity_resolver", lambda: SimpleNamespace(resolve=_resolve))

        cmd = CreateSessionCommand(
            session_id="headless-customer",
            headless=True,
            native_session_id="native-456",
            project_path=str(project_path),
            origin="terminal",
            origin_metadata=TerminalOriginMetadata(email="customer@example.com"),
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                agent="codex",
                native_session_id="native-456",
            ),
        )

        result = await _session.create_session(cmd, SimpleNamespace())

        create_call = db.create_session.await_args
        assert create_call.kwargs["project_path"] == str(help_desk)
        assert create_call.kwargs["subdir"] is None
        assert create_call.kwargs["working_slug"] is None
        assert create_call.kwargs["tmux_session_name"] == _EMPTY
        assert create_call.kwargs["lifecycle_status"] == _LIFECYCLE_HEADLESS
        assert create_call.kwargs["system_role"] is None
        assert create_call.kwargs["human_role"] == _ROLE_CUSTOMER
        assert result["tmux_session_name"] == _EMPTY


class TestSessionListing:
    @pytest.mark.unit
    async def test_list_sessions_builds_snapshots_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(lifecycle_status="", thinking_mode=None)
        session.last_message_sent = "ping"
        db = SimpleNamespace(list_sessions=AsyncMock(return_value=[session]))
        config = SimpleNamespace(computer=SimpleNamespace(name="local"))
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "config", config)
        monkeypatch.setattr(_snapshot, "get_last_output_summary", MagicMock(return_value="summary"))

        result = await _session.list_sessions()

        assert len(result) == 1
        assert result[0].thinking_mode == _THINKING_SLOW
        assert result[0].status == _LIFECYCLE_ACTIVE
        assert result[0].computer == _LOCAL
        assert result[0].last_output_summary == _OUTPUT_SUMMARY

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

        assert len(result) == 1
        assert result[0].name == _PROJECT_EXISTING
        assert result[0].path == str(existing)

    @pytest.mark.unit
    async def test_list_projects_with_todos_attaches_project_todos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        project = ProjectInfo(name="Existing", path="/tmp/project")
        todo = TodoDTO(slug="todo-1", status="pending", has_requirements=False, has_impl_plan=False)

        monkeypatch.setattr(_session, "list_projects", AsyncMock(return_value=[project]))
        monkeypatch.setattr(_session, "list_todos", AsyncMock(return_value=[todo]))

        result = await _session.list_projects_with_todos()

        assert len(result) == 1
        assert [item.slug for item in result[0].todos] == [_TODO_SLUG]


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
                bot_username=None,
            )
        )
        psutil = SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(
                total=16 * 1024**3,
                available=4 * 1024**3,
                percent=75.0,
            ),
            disk_usage=lambda _path="": SimpleNamespace(  # pyright: ignore[reportUnknownLambdaType]
                total=200 * 1024**3,
                free=50 * 1024**3,
                percent=75.0,
            ),
            cpu_percent=lambda _interval=None: 12.5,  # pyright: ignore[reportUnknownLambdaType]
        )

        monkeypatch.setattr(_session, "config", config)
        monkeypatch.setattr(_session, "psutil", psutil)

        info = await _session.get_computer_info()

        assert info.name == _LOCAL
        assert info.tmux_binary == _TMUX_BINARY
        assert info.system_stats is not None
        assert info.system_stats["memory"]["total_gb"] == 16.0
        assert info.system_stats["disk"]["free_gb"] == 50.0
        assert info.system_stats["cpu"]["percent_used"] == 12.5


class TestGetSessionData:
    @pytest.mark.unit
    async def test_missing_session_returns_error_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_session, "db", SimpleNamespace(get_session=AsyncMock(return_value=None)))

        result = cast(
            dict[str, object],  # guard: loose-dict — test payload assertion
            await _session.get_session_data(GetSessionDataCommand(session_id="missing")),
        )

        assert result["status"] == _STATUS_ERROR
        assert isinstance(result["error"], str)
        assert result["error"] != ""

    @pytest.mark.unit
    async def test_missing_native_log_uses_tmux_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(native_log_file=None, last_output_at=None)
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        tmux_bridge = SimpleNamespace(
            capture_pane=AsyncMock(return_value="\x1b[31mhello world\x1b[0m"), FALLBACK_CAPTURE_LINES=40
        )

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "tmux_bridge", tmux_bridge)

        result = cast(
            dict[str, object],  # guard: loose-dict — test payload assertion
            await _session.get_session_data(GetSessionDataCommand(session_id=session.session_id, tail_chars=5)),
        )

        assert result["status"] == _STATUS_SUCCESS
        # Exact equality to the de-ANSI'd tail proves the escape codes were stripped.
        assert result["messages"] == _MESSAGES_WORLD
        tmux_bridge.capture_pane.assert_awaited_once_with(
            session.tmux_session_name,
            capture_lines=_session.tmux_bridge.FALLBACK_CAPTURE_LINES,
        )

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

        result = cast(
            dict[str, object],  # guard: loose-dict — test payload assertion
            await _session.get_session_data(GetSessionDataCommand(session_id=session.session_id, tail_chars=200)),
        )

        assert result["status"] == _STATUS_SUCCESS
        assert result["messages"] == _MESSAGES_TRANSCRIPT


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

        assert result["status"] == _STATUS_SUCCESS
        event_bus.emit.assert_called_once()
        assert event_bus.emit.call_args.args[0] == TeleClaudeEvents.SESSION_CLOSED
        terminate_session.assert_not_awaited()

    @pytest.mark.unit
    async def test_closing_session_without_closed_at_is_finalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # "closing" with no closed_at is NOT terminal — finalize via terminate_session
        # (sets closed_at) instead of replaying, else it resurfaces from cached snapshots.
        session = make_session(lifecycle_status=_LIFECYCLE_CLOSING, closed_at=None)
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        event_bus = SimpleNamespace(emit=MagicMock())
        terminate_session = AsyncMock(return_value=True)

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "event_bus", event_bus)
        monkeypatch.setattr(_session, "terminate_session", terminate_session)

        result = await _session.end_session(CloseSessionCommand(session_id=session.session_id), SimpleNamespace())

        assert result["status"] == _STATUS_SUCCESS
        terminate_session.assert_awaited_once()
        event_bus.emit.assert_not_called()

    @pytest.mark.unit
    async def test_in_flight_close_returns_success_without_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # terminate_session returns False when a close is already in flight: report
        # success (the in-progress close finalizes) and do NOT replay the closed event.
        session = make_session(lifecycle_status=_LIFECYCLE_CLOSING, closed_at=None)
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        event_bus = SimpleNamespace(emit=MagicMock())
        terminate_session = AsyncMock(return_value=False)

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_session, "event_bus", event_bus)
        monkeypatch.setattr(_session, "terminate_session", terminate_session)

        result = await _session.end_session(CloseSessionCommand(session_id=session.session_id), SimpleNamespace())

        assert result["status"] == _STATUS_SUCCESS
        terminate_session.assert_awaited_once()
        event_bus.emit.assert_not_called()


class TestCloseSession:
    @pytest.mark.unit
    async def test_closing_session_without_closed_at_is_finalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # close_session is the actual TUI 'k' / `telec sessions end` path.
        session = make_session(lifecycle_status=_LIFECYCLE_CLOSING, closed_at=None)
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        event_bus = SimpleNamespace(emit=MagicMock())
        terminate_session = AsyncMock(return_value=True)
        config = SimpleNamespace(computer=SimpleNamespace(name=_LOCAL))

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_utils, "db", db)  # close_session resolves the session via @with_session
        monkeypatch.setattr(_session, "event_bus", event_bus)
        monkeypatch.setattr(_session, "terminate_session", terminate_session)
        monkeypatch.setattr(_session, "config", config)

        await _session.close_session(CloseSessionCommand(session_id=session.session_id), SimpleNamespace())

        terminate_session.assert_awaited_once()

    @pytest.mark.unit
    async def test_truly_closed_replays_without_terminating(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(lifecycle_status=_LIFECYCLE_CLOSED, closed_at=datetime.now(UTC))
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        event_bus = SimpleNamespace(emit=MagicMock())
        terminate_session = AsyncMock(return_value=True)
        config = SimpleNamespace(computer=SimpleNamespace(name=_LOCAL))

        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_utils, "db", db)
        monkeypatch.setattr(_session, "event_bus", event_bus)
        monkeypatch.setattr(_session, "terminate_session", terminate_session)
        monkeypatch.setattr(_session, "config", config)

        await _session.close_session(CloseSessionCommand(session_id=session.session_id), SimpleNamespace())

        terminate_session.assert_not_awaited()
        event_bus.emit.assert_called_once()

    @pytest.mark.unit
    async def test_stale_remote_name_but_locally_present_closes_locally(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # computer_name drifted (e.g. host renamed Mac->MozBook) but the tmux session is
        # live on this host: close locally instead of forwarding to a phantom peer.
        session = make_session(lifecycle_status=_LIFECYCLE_ACTIVE, closed_at=None)  # computer_name="local"
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        terminate_session = AsyncMock(return_value=True)
        forward_command = AsyncMock()
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_utils, "db", db)
        monkeypatch.setattr(_session, "event_bus", SimpleNamespace(emit=MagicMock()))
        monkeypatch.setattr(_session, "terminate_session", terminate_session)
        monkeypatch.setattr(_session, "forward_command", forward_command)
        monkeypatch.setattr(_session, "config", SimpleNamespace(computer=SimpleNamespace(name="MozBook")))
        monkeypatch.setattr(_session.tmux_bridge, "session_exists", AsyncMock(return_value=True))

        await _session.close_session(CloseSessionCommand(session_id=session.session_id), SimpleNamespace())

        forward_command.assert_not_awaited()
        terminate_session.assert_awaited_once()

    @pytest.mark.unit
    async def test_remote_name_and_not_locally_present_forwards(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(lifecycle_status=_LIFECYCLE_ACTIVE, closed_at=None)
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        terminate_session = AsyncMock(return_value=True)
        forward_command = AsyncMock()
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(_utils, "db", db)
        monkeypatch.setattr(_session, "event_bus", SimpleNamespace(emit=MagicMock()))
        monkeypatch.setattr(_session, "terminate_session", terminate_session)
        monkeypatch.setattr(_session, "forward_command", forward_command)
        monkeypatch.setattr(_session, "config", SimpleNamespace(computer=SimpleNamespace(name="MozBook")))
        monkeypatch.setattr(_session.tmux_bridge, "session_exists", AsyncMock(return_value=False))

        await _session.close_session(CloseSessionCommand(session_id=session.session_id), SimpleNamespace())

        forward_command.assert_awaited_once()
        terminate_session.assert_not_awaited()
