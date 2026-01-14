"""Unit tests for REST adapter endpoints."""

# type: ignore[explicit-any, unused-ignore] - test uses mocked adapters and dynamic types

import shlex
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.adapters.rest_adapter import RESTAdapter
from teleclaude.core.models import ComputerInfo, ProjectInfo, SessionSummary, TodoInfo


@pytest.fixture
def mock_adapter_client():  # type: ignore[explicit-any, unused-ignore]
    """Create mock AdapterClient."""
    client = MagicMock()
    client.handle_event = AsyncMock()
    return client


@pytest.fixture
def mock_cache():  # type: ignore[explicit-any, unused-ignore]
    """Create mock DaemonCache."""
    cache = MagicMock()
    cache.get_sessions = MagicMock(return_value=[])
    cache.get_computers = MagicMock(return_value=[])
    cache.get_projects = MagicMock(return_value=[])
    cache.get_todos = MagicMock(return_value=[])
    cache.is_stale = MagicMock(return_value=False)
    return cache


@pytest.fixture
def rest_adapter(mock_adapter_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Create RESTAdapter instance with mocked client and cache."""
    adapter = RESTAdapter(client=mock_adapter_client, cache=mock_cache)
    return adapter


@pytest.fixture
def test_client(rest_adapter):  # type: ignore[explicit-any, unused-ignore]
    """Create TestClient for REST adapter."""
    return TestClient(rest_adapter.app)


def test_health_endpoint(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test health check endpoint."""
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_sessions_success(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions returns local sessions with computer field."""
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_sessions", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.return_value = [
            SessionSummary(
                session_id="sess-1",
                title="Test Session",
                origin_adapter="telegram",
                working_directory="~",
                thinking_mode="slow",
                active_agent=None,
                status="active",
            ),
        ]
        # Mock cache to return one remote session
        mock_cache.get_sessions.return_value = [
            SessionSummary(
                session_id="sess-2",
                title="Remote Session",
                computer="remote",
                origin_adapter="telegram",
                working_directory="~",
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
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_sessions", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.return_value = [
            SessionSummary(
                session_id="sess-1",
                title="Local",
                origin_adapter="telegram",
                working_directory="~",
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
    adapter = RESTAdapter(client=mock_adapter_client, cache=None)
    client = TestClient(adapter.app)

    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_sessions", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.return_value = [
            SessionSummary(
                session_id="sess-1",
                title="Local",
                origin_adapter="telegram",
                working_directory="~",
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
async def test_refresh_remote_cache_notifies_projects(rest_adapter, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Initial refresh should notify clients to refresh projects."""
    redis_adapter = MagicMock(spec=RedisAdapter)
    redis_adapter.refresh_remote_snapshot = AsyncMock()
    mock_adapter_client.adapters = {"redis": redis_adapter}
    rest_adapter._on_cache_change = MagicMock()

    await rest_adapter._refresh_remote_cache_and_notify()

    redis_adapter.refresh_remote_snapshot.assert_awaited_once()
    rest_adapter._on_cache_change.assert_called_once_with("projects_updated", {"computer": None})


def test_create_session_success(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session endpoint."""
    mock_adapter_client.handle_event.return_value = {
        "status": "success",
        "data": {
            "session_id": "new-sess",
            "tmux_session_name": "tc_new",
        },
    }

    response = test_client.post(
        "/sessions",
        json={
            "computer": "local",
            "project_dir": "/path/to/project",
            "agent": "claude",
            "thinking_mode": "slow",
            "title": "Test Session",
            "message": "Hello",
        },
    )
    if response.status_code != 200:
        print(f"Validation error: {response.json()}")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "new-sess"
    assert data["tmux_session_name"] == "tc_new"
    assert data["status"] == "success"

    call_args = mock_adapter_client.handle_event.call_args
    assert call_args.kwargs["payload"]["args"] == ["Test Session"]
    assert call_args.kwargs["metadata"].auto_command == "agent_then_message claude slow Hello"


def test_create_session_derives_title_from_message(  # type: ignore[explicit-any, unused-ignore]
    test_client, mock_adapter_client
):
    """Test create_session derives title from command message."""
    mock_adapter_client.handle_event.return_value = {"status": "success", "data": {"session_id": "sess"}}

    response = test_client.post(
        "/sessions",
        json={
            "computer": "local",
            "project_dir": "/path",
            "message": "/next-work feature-123",
        },
    )
    assert response.status_code == 200

    # Verify handle_event was called with title from message
    call_args = mock_adapter_client.handle_event.call_args
    assert call_args.kwargs["metadata"].title == "/next-work feature-123"
    expected_message = shlex.quote("/next-work feature-123")
    assert call_args.kwargs["metadata"].auto_command == f"agent_then_message claude slow {expected_message}"


def test_create_session_defaults_title_to_untitled(  # type: ignore[explicit-any, unused-ignore]
    test_client, mock_adapter_client
):
    """Test create_session defaults to 'Untitled' when no title/message."""
    mock_adapter_client.handle_event.return_value = {"status": "success", "data": {"session_id": "sess"}}

    response = test_client.post(
        "/sessions",
        json={
            "computer": "local",
            "project_dir": "/path",
        },
    )
    assert response.status_code == 200

    call_args = mock_adapter_client.handle_event.call_args
    assert call_args.kwargs["metadata"].title == "Untitled"
    assert call_args.kwargs["payload"]["args"] == ["Untitled"]
    assert call_args.kwargs["metadata"].auto_command == "agent claude slow"


def test_create_session_uses_auto_command_override(  # type: ignore[explicit-any, unused-ignore]
    test_client, mock_adapter_client
):
    """Test create_session uses explicit auto_command when provided."""
    mock_adapter_client.handle_event.return_value = {"status": "success", "data": {"session_id": "sess"}}

    response = test_client.post(
        "/sessions",
        json={
            "computer": "local",
            "project_dir": "/path",
            "auto_command": "agent gemini med",
            "message": "ignored",
        },
    )
    assert response.status_code == 200

    call_args = mock_adapter_client.handle_event.call_args
    assert call_args.kwargs["metadata"].auto_command == "agent gemini med"


def test_create_session_populates_tmux_session_name(  # type: ignore[explicit-any, unused-ignore]
    test_client, mock_adapter_client
):
    """Test create_session fills tmux_session_name when handler omits it."""
    mock_adapter_client.handle_event.return_value = {"status": "success", "data": {"session_id": "sess-1"}}

    class _Session:
        tmux_session_name = "tc_1234"

    with patch("teleclaude.adapters.rest_adapter.db.get_session", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _Session()

        response = test_client.post(
            "/sessions",
            json={
                "computer": "local",
                "project_dir": "/path",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tmux_session_name"] == "tc_1234"


def test_end_session_success(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test end_session endpoint calls command handler."""
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_end_session", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.return_value = {"status": "success", "message": "Session ended"}

        response = test_client.delete("/sessions/sess-123?computer=local")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify handler was called with session_id and client
        mock_handler.assert_called_once()
        call_args = mock_handler.call_args
        assert call_args.args[0] == "sess-123"
        assert call_args.args[1] == mock_adapter_client


def test_send_message_success(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test send_message endpoint."""
    mock_adapter_client.handle_event.return_value = {"result": "Message sent"}

    response = test_client.post(
        "/sessions/sess-123/message?computer=local",
        json={"message": "Hello AI"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["result"]["result"] == "Message sent"

    # Verify handle_event was called
    call_args = mock_adapter_client.handle_event.call_args
    assert call_args.kwargs["event"] == "message"
    assert call_args.kwargs["payload"]["session_id"] == "sess-123"
    assert call_args.kwargs["payload"]["text"] == "Hello AI"


def test_get_transcript_success(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test get_transcript endpoint."""
    mock_adapter_client.handle_event.return_value = {
        "transcript": "AI output here",
        "status": "success",
    }

    response = test_client.get("/sessions/sess-123/transcript?computer=local&tail_chars=1000")
    assert response.status_code == 200
    data = response.json()
    assert "transcript" in data

    # Verify handle_event was called with tail_chars
    call_args = mock_adapter_client.handle_event.call_args
    assert call_args.kwargs["event"] == "get_session_data"
    assert call_args.kwargs["payload"]["args"] == ["1000"]


def test_list_computers_success(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_computers returns local + cached computers."""
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_get_computer_info", new_callable=AsyncMock
    ) as mock_handler:
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
    adapter = RESTAdapter(client=mock_adapter_client, cache=None)
    client = TestClient(adapter.app)

    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_get_computer_info", new_callable=AsyncMock
    ) as mock_handler:
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
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_projects", new_callable=AsyncMock
    ) as mock_handler:
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
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_projects", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.return_value = [ProjectInfo(name="project1", path="/path1", computer="local")]
        mock_cache.get_projects.return_value = []

        response = test_client.get("/projects?computer=local")
        assert response.status_code == 200
        # Verify cache was queried with computer filter
        mock_cache.get_projects.assert_called_once_with("local", include_stale=True)


def test_list_projects_without_cache(mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects works without cache (local-only mode)."""
    adapter = RESTAdapter(client=mock_adapter_client, cache=None)
    client = TestClient(adapter.app)

    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_projects", new_callable=AsyncMock
    ) as mock_handler:
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


def test_list_todos_local_success(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_todos endpoint returns todos for local project."""
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_todos", new_callable=AsyncMock
    ) as mock_todos:
        mock_todos.return_value = [
            TodoInfo(slug="feature-1", status="pending", description="Implement feature 1"),
        ]

        response = test_client.get("/todos", params={"project": "/path/to/project1"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["slug"] == "feature-1"


def test_list_todos_remote_cached(test_client, mock_cache):  # type: ignore[explicit-any, unused-ignore]
    """Test list_todos returns cached todos for remote projects."""
    mock_cache.get_todos.return_value = [
        TodoInfo(slug="remote-1", status="pending", description="Remote todo"),
    ]

    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_todos", new_callable=AsyncMock
    ) as mock_todos:
        response = test_client.get(
            "/todos",
            params={"project": "/remote/path", "computer": "remote"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["slug"] == "remote-1"
        mock_cache.get_todos.assert_called_once_with("remote", "/remote/path")
        mock_todos.assert_not_called()


def test_list_todos_missing_project(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_todos requires a project query param."""
    response = test_client.get("/todos")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_adapter_lifecycle(rest_adapter):  # type: ignore[explicit-any, unused-ignore]
    """Test adapter start/stop lifecycle."""
    # Start adapter
    await rest_adapter.start()
    assert rest_adapter.server is not None
    assert rest_adapter.server_task is not None

    # Stop adapter
    await rest_adapter.stop()
    assert rest_adapter.server.should_exit is True


def test_adapter_key():  # type: ignore[explicit-any, unused-ignore]
    """Test adapter key is 'rest'."""
    from teleclaude.adapters.rest_adapter import RESTAdapter

    assert RESTAdapter.ADAPTER_KEY == "rest"


# ==================== Error Path Tests ====================


def test_list_sessions_handler_exception(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions returns 500 when command handler raises exception."""
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_sessions", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.side_effect = Exception("Connection failed")

        response = test_client.get("/sessions")
        assert response.status_code == 500
        assert "Failed to list sessions" in response.json()["detail"]


def test_create_session_handler_exception(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session returns 500 when handler raises exception."""
    mock_adapter_client.handle_event.side_effect = Exception("Session creation failed")

    response = test_client.post(
        "/sessions",
        json={"computer": "local", "project_dir": "/path/to/project"},
    )
    assert response.status_code == 500
    assert "Failed to create session" in response.json()["detail"]


def test_send_message_handler_exception(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test send_message returns 500 when handler raises exception."""
    mock_adapter_client.handle_event.side_effect = Exception("Message delivery failed")

    response = test_client.post(
        "/sessions/sess-123/message",
        json={"message": "Hello"},
    )
    assert response.status_code == 500
    assert "Failed to send message" in response.json()["detail"]


def test_get_transcript_handler_exception(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test get_transcript returns 500 when handler raises exception."""
    mock_adapter_client.handle_event.side_effect = Exception("Transcript fetch failed")

    response = test_client.get("/sessions/sess-123/transcript")
    assert response.status_code == 500
    assert "Failed to get transcript" in response.json()["detail"]


def test_list_computers_handler_exception(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_computers returns 500 when command handler raises exception."""
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_get_computer_info", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.side_effect = Exception("Computer info failed")

        response = test_client.get("/computers")
        assert response.status_code == 500
        assert "Failed to list computers" in response.json()["detail"]


def test_list_projects_handler_exception(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects returns 500 when command handler raises exception."""
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_list_projects", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.side_effect = Exception("Project list failed")

        response = test_client.get("/projects")
        assert response.status_code == 500
        assert "Failed to list projects" in response.json()["detail"]


def test_end_session_handler_exception(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test end_session returns 500 when command handler raises exception."""
    with patch(
        "teleclaude.adapters.rest_adapter.command_handlers.handle_end_session", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.side_effect = Exception("Session not found")

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
        json={"computer": "", "project_dir": "/path/to/project"},
    )
    assert response.status_code == 422


def test_create_session_single_char_computer_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects single character computer name."""
    response = test_client.post(
        "/sessions",
        json={"computer": "x", "project_dir": "/path/to/project"},
    )
    assert response.status_code == 422


def test_create_session_empty_project_dir_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects empty project_dir."""
    response = test_client.post(
        "/sessions",
        json={"computer": "local", "project_dir": ""},
    )
    assert response.status_code == 422


def test_create_session_single_char_project_dir_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects single character project_dir."""
    response = test_client.post(
        "/sessions",
        json={"computer": "local", "project_dir": "/"},
    )
    assert response.status_code == 422


def test_create_session_missing_computer_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects missing computer field."""
    response = test_client.post(
        "/sessions",
        json={"project_dir": "/path/to/project"},
    )
    assert response.status_code == 422


def test_create_session_missing_project_dir_rejected(test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session rejects missing project_dir field."""
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
            "project_dir": "/path/to/project",
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
            "project_dir": "/path/to/project",
            "thinking_mode": "turbo",
        },
    )
    assert response.status_code == 422
