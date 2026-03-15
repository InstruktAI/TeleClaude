"""Characterization tests for teleclaude.core.command_handlers._utils."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.core.command_handlers import _utils
from teleclaude.core.models import Session


def make_session(
    *,
    session_id: str = "sess-001",
    computer_name: str = "local",
    tmux_session_name: str = "tc-sess-001",
    title: str = "Session",
) -> Session:
    """Build a concrete session for handler characterization tests."""
    return Session(
        session_id=session_id,
        computer_name=computer_name,
        tmux_session_name=tmux_session_name,
        title=title,
    )


class TestWithSession:
    @pytest.mark.unit
    async def test_missing_session_id_raises_value_error(self) -> None:
        decorated = _utils.with_session(AsyncMock())

        with pytest.raises(ValueError):
            await decorated(SimpleNamespace())

    @pytest.mark.unit
    async def test_missing_session_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = SimpleNamespace(get_session=AsyncMock(return_value=None))
        monkeypatch.setattr(_utils, "db", db)

        decorated = _utils.with_session(AsyncMock())

        with pytest.raises(RuntimeError):
            await decorated(SimpleNamespace(session_id="sess-404"))

    @pytest.mark.unit
    async def test_loaded_session_is_injected_into_wrapped_handler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        monkeypatch.setattr(_utils, "db", db)

        captured: list[object] = []

        async def handler(
            injected_session: Session,
            cmd: object,
            extra: object,
            *,
            flag: bool,
        ) -> tuple[str, bool]:
            captured.extend([injected_session, cmd, extra, flag])
            return injected_session.session_id, flag

        decorated = _utils.with_session(handler)
        cmd = SimpleNamespace(session_id="sess-001")

        result = await decorated(cmd, "payload", flag=True)

        assert result == ("sess-001", True)
        assert captured == [session, cmd, "payload", True]
