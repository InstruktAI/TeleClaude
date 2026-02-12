"""Unit tests for access control and jailing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.command_handlers import create_session
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import SessionLaunchIntent, SessionLaunchKind
from teleclaude.types.commands import CreateSessionCommand


@pytest.fixture
def mock_db():
    with patch("teleclaude.core.command_handlers.db") as mock:
        yield mock


@pytest.fixture
def mock_resolver():
    with patch("teleclaude.core.command_handlers.get_identity_resolver") as mock:
        yield mock


@pytest.mark.asyncio
async def test_create_session_unauthorized_jail(mock_db, mock_resolver):
    mock_resolver.return_value.resolve.return_value = None  # Unauthorized

    cmd = CreateSessionCommand(
        project_path="/tmp/foo",
        launch_intent=SessionLaunchIntent(kind=SessionLaunchKind.AGENT),
        title="test",
        origin="web",
        channel_metadata={},
    )

    mock_session = MagicMock()
    mock_session.session_id = "123"
    mock_db.create_session = AsyncMock(return_value=mock_session)

    # Mock resolve_working_dir to avoid filesystem checks
    with (
        patch("teleclaude.core.command_handlers.resolve_working_dir", return_value="/tmp/resolved"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_dir", return_value=True),
        patch("pathlib.Path.is_absolute", return_value=True),
    ):
        await create_session(cmd, AsyncMock())

    # Verify db.create_session called with help-desk path
    args, kwargs = mock_db.create_session.call_args
    assert "help-desk" in kwargs["project_path"]
    assert kwargs["human_role"] is None


@pytest.mark.asyncio
async def test_create_session_authorized(mock_db, mock_resolver):
    mock_resolver.return_value.resolve.return_value = IdentityContext(
        person_name="Alice", person_role="admin", platform="telegram"
    )

    cmd = CreateSessionCommand(
        project_path="/tmp/foo",
        launch_intent=SessionLaunchIntent(kind=SessionLaunchKind.AGENT),
        title="test",
        origin="telegram",
        channel_metadata={},
    )

    mock_session = MagicMock()
    mock_session.session_id = "123"
    mock_db.create_session = AsyncMock(return_value=mock_session)

    with (
        patch("teleclaude.core.command_handlers.resolve_working_dir", return_value="/tmp/foo"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_dir", return_value=True),
        patch("pathlib.Path.is_absolute", return_value=True),
    ):
        await create_session(cmd, AsyncMock())

    # Verify path preserved
    args, kwargs = mock_db.create_session.call_args
    assert kwargs["project_path"] == "/tmp/foo"
    assert kwargs["human_role"] == "admin"
