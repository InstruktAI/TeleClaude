"""Characterization tests for teleclaude.core.command_handlers._keys."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.command_handlers import _keys
from teleclaude.core.command_handlers import _utils as command_utils
from teleclaude.core.models import Session
from teleclaude.types.commands import KeysCommand


def make_session(
    *,
    session_id: str = "sess-001",
    tmux_session_name: str = "tc-sess-001",
    lifecycle_status: str = "active",
    project_path: str | None = "/tmp/project",
    subdir: str | None = None,
    active_agent: str | None = "codex",
) -> Session:
    """Build a concrete session for key-handler tests."""
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=tmux_session_name,
        title="Session",
        lifecycle_status=lifecycle_status,
        project_path=project_path,
        subdir=subdir,
        active_agent=active_agent,
    )


def patch_handler_db(monkeypatch: pytest.MonkeyPatch, db: SimpleNamespace) -> None:
    """Patch both the handler module and shared decorator to use a fake DB."""
    monkeypatch.setattr(_keys, "db", db)
    monkeypatch.setattr(command_utils, "db", db)


class TestEnsureTmuxForHeadless:
    @pytest.mark.unit
    async def test_active_session_with_tmux_is_returned_unchanged(self) -> None:
        session = make_session()

        result = await _keys._ensure_tmux_for_headless(
            session,
            SimpleNamespace(send_message=AsyncMock()),
            None,
            resume_native=False,
        )

        assert result is session

    @pytest.mark.unit
    async def test_missing_project_path_reports_adoption_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(tmux_session_name="", lifecycle_status="headless", project_path=None, active_agent=None)
        db = SimpleNamespace(
            update_session=AsyncMock(),
            get_session=AsyncMock(return_value=None),
            get_voice=AsyncMock(return_value=None),
        )
        client = SimpleNamespace(send_message=AsyncMock())

        monkeypatch.setattr(_keys, "db", db)

        result = await _keys._ensure_tmux_for_headless(
            session,
            client,
            None,
            resume_native=False,
        )

        assert result is None
        assert session.tmux_session_name.startswith(_keys.TMUX_SESSION_PREFIX)
        db.update_session.assert_awaited_once()
        client.send_message.assert_awaited_once()


class TestKeysDispatch:
    @pytest.mark.unit
    async def test_headless_cancel_adopts_then_dispatches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(lifecycle_status="headless")
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        adopted = AsyncMock(return_value=session)
        cancel_command = AsyncMock()
        start_polling = AsyncMock()
        client = SimpleNamespace(send_message=AsyncMock())

        monkeypatch.setattr(_keys, "db", db)
        monkeypatch.setattr(_keys, "_ensure_tmux_for_headless", adopted)
        monkeypatch.setattr(_keys, "cancel_command", cancel_command)

        cmd = KeysCommand(session_id=session.session_id, key="cancel")

        await _keys.keys(cmd, client, start_polling)

        adopted.assert_awaited_once_with(session, client, start_polling, resume_native=True)
        cancel_command.assert_awaited_once_with(cmd, start_polling, double=False)


class TestEscapeCommand:
    @pytest.mark.unit
    async def test_escape_with_text_sends_pasted_input_and_starts_polling(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session), update_last_activity=AsyncMock())
        tmux_io = SimpleNamespace(
            send_escape=AsyncMock(return_value=True),
            is_process_running=AsyncMock(return_value=False),
            wrap_bracketed_paste=MagicMock(return_value="<wrapped>"),
            process_text=AsyncMock(return_value=True),
        )
        start_polling = AsyncMock()

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_keys, "tmux_io", tmux_io)
        monkeypatch.setattr(_keys, "resolve_working_dir", MagicMock(return_value="/tmp/project"))

        cmd = KeysCommand(session_id=session.session_id, key="escape", args=["echo", "ok"])

        await _keys.escape_command(cmd, start_polling)

        tmux_io.send_escape.assert_awaited_once_with(session)
        tmux_io.process_text.assert_awaited_once_with(
            session,
            "<wrapped>",
            working_dir="/tmp/project",
            active_agent="codex",
        )
        db.update_last_activity.assert_awaited_once_with(session.session_id)
        start_polling.assert_awaited_once_with(session.session_id, session.tmux_session_name)


class TestRepeatCountCommands:
    @pytest.mark.unit
    async def test_shift_tab_invalid_count_defaults_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        execute_control_key = AsyncMock(return_value=True)

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_keys, "_execute_control_key", execute_control_key)

        cmd = KeysCommand(session_id=session.session_id, key="shift_tab", args=["foo"])

        await _keys.shift_tab_command(cmd, AsyncMock())

        execute_control_key.assert_awaited_once_with(_keys.tmux_io.send_shift_tab, session, 1)

    @pytest.mark.unit
    async def test_backspace_zero_count_defaults_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        execute_control_key = AsyncMock(return_value=True)

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_keys, "_execute_control_key", execute_control_key)

        cmd = KeysCommand(session_id=session.session_id, key="backspace", args=["0"])

        await _keys.backspace_command(cmd, AsyncMock())

        execute_control_key.assert_awaited_once_with(_keys.tmux_io.send_backspace, session, 1)

    @pytest.mark.unit
    async def test_arrow_key_uses_explicit_repeat_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        execute_control_key = AsyncMock(return_value=True)

        patch_handler_db(monkeypatch, db)
        monkeypatch.setattr(_keys, "_execute_control_key", execute_control_key)

        cmd = KeysCommand(session_id=session.session_id, key="key_up", args=["3"])

        await _keys.arrow_key_command(cmd, AsyncMock(), "up")

        execute_control_key.assert_awaited_once_with(_keys.tmux_io.send_arrow_key, session, "up", 3)
