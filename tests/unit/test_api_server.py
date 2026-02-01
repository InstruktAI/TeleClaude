"""Unit tests for API server endpoints."""

# type: ignore[explicit-any, unused-ignore] - test uses mocked adapters and dynamic types
import uuid
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from teleclaude.api_server import APIServer
from teleclaude.core.models import ComputerInfo, ProjectInfo, SessionSummary, TodoInfo
from teleclaude.core.origins import InputOrigin
from teleclaude.transport.redis_transport import RedisTransport


@pytest.fixture
def mock_adapter_client():  # type: ignore[explicit-any, unused-ignore]
    """Create mock AdapterClient."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_command_service():  # type: ignore[explicit-any, unused-ignore]
    """Create mock CommandService singleton."""
    commands = MagicMock()
    commands.create_session = AsyncMock()
    commands.end_session = AsyncMock()
    commands.send_message = AsyncMock()
    commands.handle_voice = AsyncMock()
    commands.handle_file = AsyncMock()
    commands.restart_agent = AsyncMock()
    return commands


@pytest.fixture
def mock_cache():  # type: ignore[explicit-any, unused-ignore]
    """Create mock DaemonCache."""
    cache = MagicMock()
    cache.get_sessions = MagicMock(return_value=[])
    cache.get_computers = MagicMock(return_value=[])
    cache.get_projects = MagicMock(return_value=[])
    cache.get_todos = MagicMock(return_value=[])
    cache.get_todo_entries = MagicMock(return_value=[])
    cache.is_stale = MagicMock(return_value=False)
    return cache


@pytest.fixture
def api_server(mock_adapter_client, mock_cache, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Create APIServer instance with mocked client and cache."""
    socket_path = f"/tmp/teleclaude-api-test-{uuid.uuid4().hex}.sock"
    with patch("teleclaude.api_server.get_command_service", return_value=mock_command_service):
        adapter = APIServer(client=mock_adapter_client, cache=mock_cache, socket_path=socket_path)
        yield adapter


@pytest.fixture
def test_client(api_server):  # type: ignore[explicit-any, unused-ignore]
    """Create TestClient for API server."""
    return TestClient(api_server.app)


def test_health_endpoint(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test health check endpoint."""
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_sessions_success(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions returns local sessions with computer field."""
    with patch("teleclaude.api_server.command_handlers.list_sessions", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = [
            SessionSummary(
                session_id="sess-1",
                title="Test Session",
                last_input_origin=InputOrigin.TELEGRAM.value,
                project_path="~",
                thinking_mode="slow",
                active_agent=None,
                status="active",
            ),
        ]
        # Mock cache to return one duplicate + one remote session
        mock_cache.get_sessions.return_value = [
            SessionSummary(
                session_id="sess-1",
                title="Duplicate Session",
                computer="remote",
                last_input_origin=InputOrigin.TELEGRAM.value,
                project_path="~",
                thinking_mode="slow",
                active_agent=None,
                status="active",
            ),
            SessionSummary(
                session_id="sess-2",
                title="Remote Session",
                computer="remote",
                last_input_origin=InputOrigin.TELEGRAM.value,
                project_path="~",
                thinking_mode="slow",
                active_agent=None,
                status="active",
            ),
        ]

        response = test_client.get("/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # First session is local
        assert data[0]["session_id"] == "sess-1"
        assert "computer" in data[0]
        # Second session is from cache
        assert data[1]["session_id"] == "sess-2"
        assert data[1]["computer"] == "remote"
        mock_handler.assert_called_once()


def test_list_sessions_with_computer_filter(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions passes computer parameter to cache."""
    with patch("teleclaude.api_server.command_handlers.list_sessions", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = [
            SessionSummary(
                session_id="sess-1",
                title="Local",
                last_input_origin=InputOrigin.TELEGRAM.value,
                project_path="~",
                thinking_mode="slow",
                active_agent=None,
                status="active",
            )
        ]
        mock_cache.get_sessions.return_value = []

        response = test_client.get("/sessions?computer=local")
        assert response.status_code == 200
        # Verify cache was queried with computer filter
        mock_cache.get_sessions.assert_called_once_with("local")


def test_list_sessions_without_cache(mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions works without cache (local-only mode)."""
    adapter = APIServer(client=mock_adapter_client, cache=None)
    client = TestClient(adapter.app)

    with patch("teleclaude.api_server.command_handlers.list_sessions", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = [
            SessionSummary(
                session_id="sess-1",
                title="Local",
                last_input_origin=InputOrigin.TELEGRAM.value,
                project_path="~",
                thinking_mode="slow",
                active_agent=None,
                status="active",
            )
        ]

        response = client.get("/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_refresh_remote_cache_notifies_projects(api_server, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Initial refresh should notify clients to refresh projects."""
    redis_adapter = MagicMock(spec=RedisTransport)
    redis_adapter.refresh_remote_snapshot = AsyncMock()
    mock_adapter_client.adapters = {"redis": redis_adapter}
    api_server._on_cache_change = MagicMock()

    await api_server._refresh_remote_cache_and_notify()

    redis_adapter.refresh_remote_snapshot.assert_awaited_once()
    api_server._on_cache_change.assert_called_once_with("projects_updated", {"computer": None})


def test_create_session_success(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session endpoint."""
    mock_command_service.create_session.return_value = {
        "session_id": "sess-123",
        "tmux_session_name": "tc_test",
    }

    response = test_client.post(
        "/sessions",
        json={
            "project_path": "/home/user/project",
            "computer": "local",
            "agent": "claude",
            "thinking_mode": "slow",
            "title": "Test Session",
            "message": "Hello",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["session_id"] == "sess-123"

    # Verify create_session was called
    call_args = mock_command_service.create_session.call_args
    cmd = call_args.args[0]
    assert cmd.project_path == "/home/user/project"
    assert cmd.title == "Test Session"


def test_create_session_derives_title_from_message(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test that create_session derives title from message if not provided."""
    mock_command_service.create_session.return_value = {
        "session_id": "sess-123",
        "tmux_session_name": "tc_123",
    }

    response = test_client.post(
        "/sessions",
        json={
            "project_path": "/home/user/project",
            "computer": "local",
            "message": "/claude",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

    # Verify title was derived
    call_args = mock_command_service.create_session.call_args
    cmd = call_args.args[0]
    assert cmd.title == "/claude"


def test_create_session_defaults_title_to_untitled(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test that create_session defaults title to 'Untitled'."""
    mock_command_service.create_session.return_value = {
        "session_id": "sess-123",
        "tmux_session_name": "tc_123",
    }

    response = test_client.post(
        "/sessions",
        json={"project_path": "/home/user/project", "computer": "local"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

    # Verify title is 'Untitled'
    call_args = mock_command_service.create_session.call_args
    cmd = call_args.args[0]
    assert cmd.title == "Untitled"


def test_create_session_uses_auto_command_override(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test that create_session uses auto_command override if provided."""
    mock_command_service.create_session.return_value = {
        "session_id": "sess-123",
        "tmux_session_name": "tc_123",
    }

    response = test_client.post(
        "/sessions",
        json={
            "project_path": "/home/user/project",
            "computer": "local",
            "auto_command": "custom_cmd",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

    # Verify auto_command on command
    call_args = mock_command_service.create_session.call_args
    cmd = call_args.args[0]
    assert cmd.auto_command == "custom_cmd"


def test_create_session_populates_tmux_session_name(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test that create_session populates tmux_session_name in response."""
    mock_command_service.create_session.return_value = {
        "session_id": "sess-123",
        "tmux_session_name": "tc_test",
    }

    response = test_client.post(
        "/sessions",
        json={"project_path": "/home/user/project", "computer": "local"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tmux_session_name"] == "tc_test"


def test_end_session_success(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test end_session endpoint calls command handler."""
    mock_command_service.end_session.return_value = {"status": "success", "message": "ok"}

    response = test_client.delete("/sessions/sess-123?computer=local")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

    # Verify internal command dispatch
    call_args = mock_command_service.end_session.call_args
    cmd = call_args.args[0]
    assert cmd.session_id == "sess-123"


def test_send_message_success(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test send_message endpoint."""
    mock_command_service.send_message.return_value = None

    response = test_client.post(
        "/sessions/sess-123/message?computer=local",
        json={"message": "Hello AI"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

    # Verify send_message was called
    call_args = mock_command_service.send_message.call_args
    cmd = call_args.args[0]
    assert cmd.session_id == "sess-123"
    assert cmd.text == "Hello AI"


def test_list_computers_success(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_computers returns local + cached computers."""
    with patch("teleclaude.api_server.command_handlers.get_computer_info", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = ComputerInfo(
            name="local",
            status="online",
            user="me",
            host="localhost",
            role="worker",
            is_local=True,
        )
        # Mock cache to return one remote computer
        mock_cache.get_computers.return_value = [
            ComputerInfo(
                name="remote",
                status="online",
                user="you",
                host="192.168.1.2",
                role="worker",
                is_local=False,
            ),
        ]

        response = test_client.get("/computers")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # First computer: local (from config)
        assert data[0]["status"] == "online"
        assert data[0]["user"] == "me"
        assert data[0]["host"] == "localhost"
        # Second computer: from cache
        assert data[1]["name"] == "remote"
        assert data[1]["status"] == "online"
        assert data[1]["user"] == "you"


def test_list_computers_without_cache(mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_computers works without cache (local-only mode)."""
    adapter = APIServer(client=mock_adapter_client, cache=None)
    client = TestClient(adapter.app)

    with patch("teleclaude.api_server.command_handlers.get_computer_info", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = ComputerInfo(
            name="local",
            status="online",
            user="me",
            host="localhost",
            role="worker",
            is_local=True,
        )

        response = client.get("/computers")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1  # Only local computer
        assert data[0]["status"] == "online"


def test_list_projects_success(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects returns local + cached projects."""
    with patch("teleclaude.api_server.command_handlers.list_projects", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = [
            ProjectInfo(name="project1", path="/path1", description="Local project", computer="local"),
        ]
        # Mock cache to return one remote project for the interested computer
        mock_cache.get_projects.return_value = [
            ProjectInfo(name="project2", path="/path2", description="Remote project", computer="RemoteComputer"),
        ]

        response = test_client.get("/projects")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "project1"
        assert data[0]["description"] == "Local project"
        mock_handler.assert_called_once()


def test_list_projects_with_computer_filter(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects filters by computer."""
    with patch("teleclaude.api_server.command_handlers.list_projects", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = [ProjectInfo(name="project1", path="/path1", computer="local")]
        mock_cache.get_projects.return_value = []

        response = test_client.get("/projects?computer=local")
        assert response.status_code == 200
        # Verify cache was queried with computer filter
        mock_cache.get_projects.assert_called_once_with("local", include_stale=True)


def test_list_projects_without_cache(mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects works without cache (local-only mode)."""
    adapter = APIServer(client=mock_adapter_client, cache=None)
    client = TestClient(adapter.app)

    with patch("teleclaude.api_server.command_handlers.list_projects", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = [ProjectInfo(name="project1", path="/path1", description="Local", computer="local")]

        response = client.get("/projects")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "project1"


def test_get_agent_availability_success(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test get_agent_availability endpoint."""
    # Patch db at the location where it's imported in the endpoint function
    with patch("teleclaude.core.db.db.get_agent_availability", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "available": False,
            "unavailable_until": "2026-01-10T12:00:00Z",
            "reason": "rate_limited",
        }

        response = test_client.get("/agents/availability")
        assert response.status_code == 200
        data = response.json()
        assert "claude" in data
        assert data["claude"]["available"] is False
        assert data["claude"]["reason"] == "rate_limited"


def test_get_agent_availability_defaults_to_available(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test agent availability defaults to available when no info."""
    with patch("teleclaude.core.db.db.get_agent_availability", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        response = test_client.get("/agents/availability")
        assert response.status_code == 200
        data = response.json()
        assert data["claude"]["available"] is True
        assert data["claude"]["unavailable_until"] is None


def test_list_todos_all_cached(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_todos returns cached todos without filters."""
    from teleclaude.core.cache import TodoCacheEntry

    mock_cache.get_todo_entries.return_value = [
        TodoCacheEntry(
            computer="remote",
            project_path="/remote/path",
            todos=[TodoInfo(slug="remote-1", status="pending", description="Remote todo")],
            is_stale=False,
        ),
    ]

    response = test_client.get("/todos")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["slug"] == "remote-1"
    assert data[0]["computer"] == "remote"
    assert data[0]["project_path"] == "/remote/path"
    mock_cache.get_todo_entries.assert_called_once_with(computer=None, project_path=None, include_stale=True)


def test_list_todos_project_filter(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_todos applies project filter when provided."""
    from teleclaude.core.cache import TodoCacheEntry

    mock_cache.get_todo_entries.return_value = [
        TodoCacheEntry(
            computer="remote",
            project_path="/remote/path",
            todos=[TodoInfo(slug="remote-1", status="pending")],
            is_stale=True,
        ),
    ]

    response = test_client.get("/todos", params={"project": "/remote/path", "computer": "remote"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["slug"] == "remote-1"
    mock_cache.get_todo_entries.assert_called_once_with(
        computer="remote",
        project_path="/remote/path",
        include_stale=True,
    )


def test_list_todos_without_cache_falls_back_to_local(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_todos falls back to local handler without cache."""
    adapter = APIServer(client=MagicMock(), cache=None)
    client = TestClient(adapter.app)

    with patch("teleclaude.api_server.command_handlers.list_todos", new_callable=AsyncMock) as mock_todos:
        mock_todos.return_value = [TodoInfo(slug="local-1", status="pending")]

        response = client.get("/todos", params={"project": "/local/path"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["slug"] == "local-1"


@pytest.mark.asyncio
async def test_adapter_lifecycle(api_server):  # type: ignore[explicit-any, unused-ignore]
    """Test adapter start/stop lifecycle."""
    # Start adapter
    await api_server.start()
    assert api_server.server is not None
    assert api_server.server_task is not None

    # Stop adapter
    await api_server.stop()
    assert api_server.server.should_exit is True


@pytest.mark.asyncio
async def test_handle_session_started_updates_cache(api_server, mock_cache):
    """Test _handle_session_started_event updates cache."""
    from teleclaude.core.events import SessionLifecycleContext
    from teleclaude.core.models import Session

    context = SessionLifecycleContext(session_id="new-sess")
    session = Session(
        session_id="new-sess",
        computer_name="local",
        tmux_session_name="tc_new",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="New Session",
    )

    with patch("teleclaude.api_server.db.get_session", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = session

        await api_server._handle_session_started_event("session_started", context)

        mock_cache.update_session.assert_called_once()
        summary = mock_cache.update_session.call_args[0][0]
        assert summary.session_id == "new-sess"
        assert summary.title == "New Session"


@pytest.mark.asyncio
async def test_handle_session_updated_updates_cache(api_server, mock_cache):
    """Test _handle_session_updated_event updates cache."""
    from teleclaude.core.events import SessionUpdatedContext
    from teleclaude.core.models import Session

    context = SessionUpdatedContext(session_id="sess-1", updated_fields={"title": "Updated"})
    session = Session(
        session_id="sess-1",
        computer_name="local",
        tmux_session_name="tc_1",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Updated",
    )

    with patch("teleclaude.api_server.db.get_session", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = session

        await api_server._handle_session_updated_event("session_updated", context)

        mock_cache.update_session.assert_called_once()
        summary = mock_cache.update_session.call_args[0][0]
        assert summary.session_id == "sess-1"
        assert summary.title == "Updated"


@pytest.mark.asyncio
async def test_handle_session_closed_updates_cache(api_server, mock_cache):
    """Test _handle_session_closed_event updates cache."""
    from teleclaude.core.events import SessionLifecycleContext

    context = SessionLifecycleContext(session_id="sess-1")

    await api_server._handle_session_closed_event("session_closed", context)

    mock_cache.remove_session.assert_called_once_with("sess-1")


def test_api_server_subscriptions(mock_adapter_client, mock_cache):
    """Test APIServer subscribes to correct events using constants."""
    from teleclaude.core.events import TeleClaudeEvents

    with (
        patch("teleclaude.api_server.event_bus.subscribe") as mock_subscribe,
        patch("teleclaude.api_server.get_command_service", return_value=MagicMock()),
    ):
        # Re-initialize to check calls
        APIServer(client=mock_adapter_client, cache=mock_cache)

        mock_subscribe.assert_any_call(TeleClaudeEvents.SESSION_UPDATED, ANY)
        mock_subscribe.assert_any_call(TeleClaudeEvents.SESSION_STARTED, ANY)
        mock_subscribe.assert_any_call(TeleClaudeEvents.SESSION_CLOSED, ANY)


# ==================== Error Path Tests ====================


def test_list_sessions_handler_exception(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions returns 500 when command handler raises exception."""
    with patch("teleclaude.api_server.command_handlers.list_sessions", new_callable=AsyncMock) as mock_handler:
        mock_handler.side_effect = Exception("Connection failed")

        response = test_client.get("/sessions")
        assert response.status_code == 500
        assert "Failed to list sessions" in response.json()["detail"]


def test_create_session_handler_exception(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session endpoint with handler exception."""
    mock_command_service.create_session.side_effect = Exception("Failed to create session")

    response = test_client.post(
        "/sessions",
        json={"project_path": "/home/user/project", "computer": "local"},
    )
    assert response.status_code == 500
    assert "Failed to create session" in response.json()["detail"]


def test_send_message_handler_exception(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test send_message endpoint with handler exception."""
    mock_command_service.send_message.side_effect = Exception("Internal error")

    response = test_client.post(
        "/sessions/sess-123/message?computer=local",
        json={"message": "Hello AI"},
    )
    assert response.status_code == 500
    assert "Internal error" in response.json()["detail"]


def test_send_voice_success(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test voice endpoint dispatches handle_voice."""
    response = test_client.post(
        "/sessions/sess-123/voice?computer=local",
        json={"file_path": "/tmp/voice.ogg", "duration": 1.2},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_command_service.handle_voice.assert_called_once()


def test_send_file_success(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test file endpoint dispatches handle_file."""
    response = test_client.post(
        "/sessions/sess-123/file?computer=local",
        json={"file_path": "/tmp/file.txt", "filename": "file.txt", "caption": "hi", "file_size": 5},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_command_service.handle_file.assert_called_once()


def test_list_computers_handler_exception(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_computers returns 500 when command handler raises exception."""
    with patch("teleclaude.api_server.command_handlers.get_computer_info", new_callable=AsyncMock) as mock_handler:
        mock_handler.side_effect = Exception("Computer info failed")

        response = test_client.get("/computers")
        assert response.status_code == 500
        assert "Failed to list computers" in response.json()["detail"]


def test_list_projects_handler_exception(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects returns 500 when command handler raises exception."""
    with patch("teleclaude.api_server.command_handlers.list_projects", new_callable=AsyncMock) as mock_handler:
        mock_handler.side_effect = Exception("Project list failed")

        response = test_client.get("/projects")
        assert response.status_code == 500
        assert "Failed to list projects" in response.json()["detail"]


def test_end_session_handler_exception(test_client, mock_command_service):  # type: ignore[explicit-any, unused-ignore]
    """Test end_session returns 500 when command handler raises exception."""
    mock_command_service.end_session = AsyncMock(side_effect=Exception("Session not found"))

    response = test_client.delete("/sessions/sess-123?computer=local")
    assert response.status_code == 500
    assert "Failed to end session" in response.json()["detail"]


def test_get_agent_availability_db_exception(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test agent availability returns error info on DB exception."""
    with patch("teleclaude.core.db.db.get_agent_availability", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Database connection failed")

        response = test_client.get("/agents/availability")
        assert response.status_code == 200
        data = response.json()
        # All agents should have available=None and error field
        assert data["claude"]["available"] is None
        assert "error" in data["claude"]
        assert "Database connection failed" in data["claude"]["error"]


# ==================== Validation Tests ====================


def test_create_session_empty_computer_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects empty computer name."""
    response = test_client.post(
        "/sessions",
        json={"computer": "", "project_path": "/path/to/project"},
    )
    assert response.status_code == 422


def test_create_session_single_char_computer_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects single character computer name."""
    response = test_client.post(
        "/sessions",
        json={"computer": "x", "project_path": "/path/to/project"},
    )
    assert response.status_code == 422


def test_create_session_empty_project_path_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects empty project_path."""
    response = test_client.post(
        "/sessions",
        json={"computer": "local", "project_path": ""},
    )
    assert response.status_code == 422


def test_create_session_single_char_project_path_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects single character project_path."""
    response = test_client.post(
        "/sessions",
        json={"computer": "local", "project_path": "/"},
    )
    assert response.status_code == 422


def test_create_session_missing_computer_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects missing computer field."""
    response = test_client.post(
        "/sessions",
        json={"project_path": "/path/to/project"},
    )
    assert response.status_code == 422


def test_create_session_missing_project_path_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects missing project_path field."""
    response = test_client.post(
        "/sessions",
        json={"computer": "local"},
    )
    assert response.status_code == 422


def test_send_message_empty_message_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test send_message rejects empty message."""
    response = test_client.post(
        "/sessions/sess-123/message",
        json={"message": ""},
    )
    assert response.status_code == 422


def test_send_message_missing_message_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test send_message rejects missing message field."""
    response = test_client.post(
        "/sessions/sess-123/message",
        json={},
    )
    assert response.status_code == 422


def test_create_session_invalid_agent_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects invalid agent value."""
    response = test_client.post(
        "/sessions",
        json={
            "computer": "local",
            "project_path": "/path/to/project",
            "agent": "invalid_agent",
        },
    )
    assert response.status_code == 422


def test_create_session_invalid_thinking_mode_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects invalid thinking_mode value."""
    response = test_client.post(
        "/sessions",
        json={
            "computer": "local",
            "project_path": "/path/to/project",
            "thinking_mode": "turbo",
        },
    )
    assert response.status_code == 422
