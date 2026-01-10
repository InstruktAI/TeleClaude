"""Unit tests for REST adapter endpoints."""

# type: ignore[explicit-any, unused-ignore] - test uses mocked adapters and dynamic types

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from teleclaude.adapters.rest_adapter import RESTAdapter


@pytest.fixture
def mock_adapter_client():  # type: ignore[explicit-any, unused-ignore]
    """Create mock AdapterClient."""
    client = MagicMock()
    client.handle_event = AsyncMock()
    return client


@pytest.fixture
def mock_mcp_server():  # type: ignore[explicit-any, unused-ignore]
    """Create mock MCP server."""
    server = MagicMock()
    server.teleclaude__list_computers = AsyncMock()
    server.teleclaude__list_projects = AsyncMock()
    server.teleclaude__end_session = AsyncMock()
    return server


@pytest.fixture
def rest_adapter(mock_adapter_client, mock_mcp_server):  # type: ignore[explicit-any, unused-ignore]
    """Create RESTAdapter instance with mocked client and MCP server."""
    adapter = RESTAdapter(client=mock_adapter_client)
    adapter.set_mcp_server(mock_mcp_server)
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


def test_list_sessions_success(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions returns sessions."""
    mock_adapter_client.handle_event.return_value = {
        "status": "success",
        "data": [{"session_id": "sess-1", "title": "Test Session"}],
    }

    response = test_client.get("/sessions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "sess-1"


def test_list_sessions_with_computer_filter(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions passes computer parameter."""
    mock_adapter_client.handle_event.return_value = {"status": "success", "data": []}

    response = test_client.get("/sessions?computer=local")
    assert response.status_code == 200
    assert response.json() == []

    # Verify handle_event was called with correct args
    mock_adapter_client.handle_event.assert_called_once()
    call_args = mock_adapter_client.handle_event.call_args
    assert call_args.kwargs["event"] == "list_sessions"
    assert call_args.kwargs["payload"]["args"] == ["local"]


def test_list_sessions_returns_empty_on_non_list_result(  # type: ignore[explicit-any, unused-ignore]
    test_client, mock_adapter_client
):
    """Test list_sessions returns 500 when handler returns non-list."""
    mock_adapter_client.handle_event.return_value = {"error": "something"}

    response = test_client.get("/sessions")
    assert response.status_code == 500
    assert "unexpected handler result type" in response.json()["detail"]


def test_create_session_success(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test create_session endpoint."""
    mock_adapter_client.handle_event.return_value = {
        "session_id": "new-sess",
        "status": "created",
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


def test_create_session_derives_title_from_message(  # type: ignore[explicit-any, unused-ignore]
    test_client, mock_adapter_client
):
    """Test create_session derives title from command message."""
    mock_adapter_client.handle_event.return_value = {"session_id": "sess"}

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


def test_create_session_defaults_title_to_untitled(  # type: ignore[explicit-any, unused-ignore]
    test_client, mock_adapter_client
):
    """Test create_session defaults to 'Untitled' when no title/message."""
    mock_adapter_client.handle_event.return_value = {"session_id": "sess"}

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


def test_end_session_success(rest_adapter, test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test end_session endpoint with MCP server."""
    mock_mcp = MagicMock()
    mock_mcp.teleclaude__end_session = AsyncMock(return_value={"status": "success", "message": "Session ended"})
    rest_adapter.set_mcp_server(mock_mcp)

    response = test_client.delete("/sessions/sess-123?computer=local")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

    mock_mcp.teleclaude__end_session.assert_called_once_with(computer="local", session_id="sess-123")


def test_end_session_no_mcp_server(mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test end_session returns 503 when MCP server not set."""
    # Create adapter without MCP server
    adapter = RESTAdapter(client=mock_adapter_client)
    client = TestClient(adapter.app)

    response = client.delete("/sessions/sess-123?computer=local")
    assert response.status_code == 503
    assert "MCP server not available" in response.json()["detail"]


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


def test_list_computers_success(test_client, mock_mcp_server):  # type: ignore[explicit-any, unused-ignore]
    """Test list_computers endpoint."""
    mock_mcp_server.teleclaude__list_computers.return_value = [
        {"name": "local", "status": "online"},
        {"name": "remote", "status": "online"},
    ]

    response = test_client.get("/computers")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "local"


def test_list_computers_no_mcp_server(mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_computers returns 503 when MCP server not available."""
    # Create adapter without MCP server
    adapter = RESTAdapter(client=mock_adapter_client)
    client = TestClient(adapter.app)

    response = client.get("/computers")
    assert response.status_code == 503
    assert "MCP server not available" in response.json()["detail"]


def test_list_projects_success(test_client, mock_mcp_server):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects endpoint."""
    mock_mcp_server.teleclaude__list_projects.return_value = [
        {"computer": "local", "name": "project1", "location": "/path1"},
        {"computer": "remote", "name": "project2", "location": "/path2"},
    ]

    response = test_client.get("/projects")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "project1"
    mock_mcp_server.teleclaude__list_projects.assert_called_once_with(None)


def test_list_projects_with_computer_filter(test_client, mock_mcp_server):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects passes computer parameter."""
    mock_mcp_server.teleclaude__list_projects.return_value = [
        {"computer": "local", "name": "project1", "location": "/path1"},
    ]

    response = test_client.get("/projects?computer=local")
    assert response.status_code == 200
    mock_mcp_server.teleclaude__list_projects.assert_called_once_with("local")


def test_list_projects_no_mcp_server(mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects returns 503 when MCP server not available."""
    # Create adapter without MCP server
    adapter = RESTAdapter(client=mock_adapter_client)
    client = TestClient(adapter.app)

    response = client.get("/projects")
    assert response.status_code == 503
    assert "MCP server not available" in response.json()["detail"]


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


def test_list_todos_success(test_client, tmp_path):  # type: ignore[explicit-any, unused-ignore]
    """Test list_todos endpoint."""
    # Create temporary roadmap.md
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    roadmap = todos_dir / "roadmap.md"
    roadmap.write_text(
        """# Roadmap

- [ ] feature-1
      Implement feature 1
- [.] feature-2
      Implement feature 2
"""
    )

    # Create feature dirs
    (todos_dir / "feature-1").mkdir()
    (todos_dir / "feature-1" / "requirements.md").touch()
    (todos_dir / "feature-2").mkdir()
    (todos_dir / "feature-2" / "implementation-plan.md").touch()

    response = test_client.get(f"/projects/{tmp_path}/todos?computer=local")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["slug"] == "feature-1"
    assert data[0]["status"] == "pending"
    assert data[0]["has_requirements"] is True
    assert data[0]["has_impl_plan"] is False
    assert data[1]["slug"] == "feature-2"
    assert data[1]["status"] == "ready"


def test_list_todos_no_roadmap(test_client, tmp_path):  # type: ignore[explicit-any, unused-ignore]
    """Test list_todos returns [] when roadmap.md doesn't exist."""
    response = test_client.get(f"/projects/{tmp_path}/todos?computer=local")
    assert response.status_code == 200
    assert response.json() == []


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


def test_list_sessions_handler_exception(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions returns 500 when handler raises exception."""
    mock_adapter_client.handle_event.side_effect = Exception("Connection failed")

    response = test_client.get("/sessions")
    assert response.status_code == 500
    assert "Failed to list sessions" in response.json()["detail"]


def test_list_sessions_handler_error_envelope(test_client, mock_adapter_client):  # type: ignore[explicit-any, unused-ignore]
    """Test list_sessions extracts error message from handler error envelope."""
    mock_adapter_client.handle_event.return_value = {
        "status": "error",
        "error": "No handler registered for event",
    }

    response = test_client.get("/sessions")
    assert response.status_code == 500
    assert "No handler registered" in response.json()["detail"]


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


def test_list_computers_handler_exception(test_client, mock_mcp_server):  # type: ignore[explicit-any, unused-ignore]
    """Test list_computers returns 500 when MCP handler raises exception."""
    mock_mcp_server.teleclaude__list_computers.side_effect = Exception("Computer info failed")

    response = test_client.get("/computers")
    assert response.status_code == 500
    assert "Failed to list computers" in response.json()["detail"]


def test_list_projects_handler_exception(test_client, mock_mcp_server):  # type: ignore[explicit-any, unused-ignore]
    """Test list_projects returns 500 when MCP handler raises exception."""
    mock_mcp_server.teleclaude__list_projects.side_effect = Exception("Project list failed")

    response = test_client.get("/projects")
    assert response.status_code == 500
    assert "Failed to list projects" in response.json()["detail"]


def test_end_session_mcp_exception(rest_adapter, test_client):  # type: ignore[explicit-any, unused-ignore]
    """Test end_session returns 500 when MCP server raises exception."""
    mock_mcp = MagicMock()
    mock_mcp.teleclaude__end_session = AsyncMock(side_effect=Exception("Session not found"))
    rest_adapter.set_mcp_server(mock_mcp)

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
