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
async def test_create_session_unidentified_preserves_project(mock_db, mock_resolver):
    mock_resolver.return_value.resolve.return_value = None

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

    # Verify missing role defaults to unrestricted project path
    args, kwargs = mock_db.create_session.call_args
    assert kwargs["project_path"] == "/tmp/foo"
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


@pytest.mark.asyncio
async def test_create_session_api_without_identity_is_unrestricted(mock_db, mock_resolver):
    """API sessions without injected role remain unrestricted."""
    mock_resolver.return_value.resolve.return_value = None

    cmd = CreateSessionCommand(
        project_path="/tmp/from-api",
        launch_intent=SessionLaunchIntent(kind=SessionLaunchKind.AGENT),
        title="test",
        origin="api",
        channel_metadata={},
    )

    mock_session = MagicMock()
    mock_session.session_id = "123"
    mock_db.create_session = AsyncMock(return_value=mock_session)

    with (
        patch("teleclaude.core.command_handlers.resolve_working_dir", return_value="/tmp/from-api"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_dir", return_value=True),
        patch("pathlib.Path.is_absolute", return_value=True),
    ):
        await create_session(cmd, AsyncMock())

    _, kwargs = mock_db.create_session.call_args
    assert kwargs["project_path"] == "/tmp/from-api"
    assert kwargs["human_role"] is None


@pytest.mark.asyncio
async def test_create_session_api_with_boundary_role_preserves_project(mock_db, mock_resolver):
    """Boundary-provided human role allows API sessions to use requested project."""
    mock_resolver.return_value.resolve.return_value = None

    cmd = CreateSessionCommand(
        project_path="/tmp/from-api",
        launch_intent=SessionLaunchIntent(kind=SessionLaunchKind.AGENT),
        title="test",
        origin="api",
        channel_metadata={"human_role": "admin"},
    )

    mock_session = MagicMock()
    mock_session.session_id = "123"
    mock_db.create_session = AsyncMock(return_value=mock_session)

    with (
        patch("teleclaude.core.command_handlers.resolve_working_dir", return_value="/tmp/from-api"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_dir", return_value=True),
        patch("pathlib.Path.is_absolute", return_value=True),
    ):
        await create_session(cmd, AsyncMock())

    _, kwargs = mock_db.create_session.call_args
    assert kwargs["project_path"] == "/tmp/from-api"
    assert kwargs["human_role"] == "admin"


@pytest.mark.asyncio
async def test_create_session_api_with_member_role_is_jailed(mock_db, mock_resolver):
    """Explicit non-admin roles are restricted to help-desk."""
    mock_resolver.return_value.resolve.return_value = None

    cmd = CreateSessionCommand(
        project_path="/tmp/from-api",
        launch_intent=SessionLaunchIntent(kind=SessionLaunchKind.AGENT),
        title="test",
        origin="api",
        channel_metadata={"human_role": "member"},
    )

    mock_session = MagicMock()
    mock_session.session_id = "123"
    mock_db.create_session = AsyncMock(return_value=mock_session)

    with (
        patch("teleclaude.core.command_handlers.resolve_working_dir", return_value="/tmp/from-api"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_dir", return_value=True),
        patch("pathlib.Path.is_absolute", return_value=True),
    ):
        await create_session(cmd, AsyncMock())

    _, kwargs = mock_db.create_session.call_args
    assert "help-desk" in kwargs["project_path"]
    assert kwargs["human_role"] == "member"
