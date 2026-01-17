"""Unit tests for Redis adapter cache pull methods."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.models import (
    ComputerInfo,
    TodoInfo,
)


@pytest.fixture(autouse=True)
def setup_test_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Setup test config for all tests in this module."""
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        """
computer:
  name: TestComputer
database:
  path: ${WORKING_DIR}/teleclaude.db
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("WORKING_DIR", str(tmp_path))


@pytest.mark.unit
@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_happy_path():
    """Test _pull_initial_sessions successfully pulls sessions from remote computers."""
    from teleclaude.transport.redis_transport import RedisTransport

    # Setup
    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock cache
    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = [
        ComputerInfo(name="RemotePC1", status="online", is_local=False),
        ComputerInfo(name="RemotePC2", status="online", is_local=False),
    ]
    # Register interest in sessions for both computers (required for per-computer pulls)
    mock_cache.get_interested_computers.return_value = ["RemotePC1", "RemotePC2"]
    adapter.cache = mock_cache

    # Mock send_request
    adapter.send_request = AsyncMock(return_value="msg-123")

    # Mock client.read_response with valid session data
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": [
                    {
                        "session_id": "sess-1",
                        "origin_adapter": "telegram",
                        "computer": "RemotePC1",
                        "status": "active",
                        "title": "Test Session",
                        "project_path": "/home/user/project",
                        "thinking_mode": "slow",
                        "active_agent": "claude",
                        "tmux_session_name": "tmux-sess-1",
                        "last_activity": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
        )
    )

    # Execute
    await adapter._pull_initial_sessions()

    # Verify cache was populated
    assert mock_cache.update_session.call_count == 2  # Called for each computer


@pytest.mark.unit
@pytest.mark.asyncio
async def test_populate_initial_cache_pulls_projects_with_todos():
    """Startup cache population should pull projects-with-todos for all peers."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    adapter.cache = MagicMock()
    adapter.discover_peers = AsyncMock(
        return_value=[
            SimpleNamespace(
                name="RemotePC1",
                last_seen="now",
                user="user1",
                host="host1",
                role="worker",
                system_stats=None,
            ),
            SimpleNamespace(
                name="RemotePC2",
                last_seen="now",
                user="user2",
                host="host2",
                role="worker",
                system_stats=None,
            ),
        ]
    )
    adapter.pull_remote_projects_with_todos = AsyncMock()

    await adapter._populate_initial_cache()

    assert adapter.pull_remote_projects_with_todos.call_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_no_cache():
    """Test _pull_initial_sessions skips when cache is unavailable."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"
    adapter.cache = None
    adapter.send_request = AsyncMock()

    # Execute
    await adapter._pull_initial_sessions()

    # Verify no requests were made
    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_timeout_continues_to_next():
    """Test _pull_initial_sessions continues to next computer on timeout."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = [
        ComputerInfo(name="RemotePC1", status="online", is_local=False),
        ComputerInfo(name="RemotePC2", status="online", is_local=False),
    ]
    # Register interest for both computers
    mock_cache.get_interested_computers.return_value = ["RemotePC1", "RemotePC2"]
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-123")

    # First call times out, second succeeds
    mock_client.read_response = AsyncMock(
        side_effect=[
            TimeoutError("timeout"),
            json.dumps({"status": "success", "data": []}),
        ]
    )

    # Execute
    await adapter._pull_initial_sessions()

    # Verify both computers were attempted
    assert adapter.send_request.call_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_malformed_response_skips():
    """Test _pull_initial_sessions skips malformed responses and continues."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = [
        ComputerInfo(name="RemotePC1", status="online", is_local=False),
    ]
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-123")
    mock_client.read_response = AsyncMock(return_value="not valid json {{{")

    # Execute (should not crash)
    await adapter._pull_initial_sessions()

    # Verify update_session was never called
    mock_cache.update_session.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_error_status_skips():
    """Test _pull_initial_sessions skips when remote returns error status."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = [
        ComputerInfo(name="RemotePC1", status="online", is_local=False),
    ]
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-123")
    mock_client.read_response = AsyncMock(return_value=json.dumps({"status": "error", "error": "Something went wrong"}))

    # Execute
    await adapter._pull_initial_sessions()

    # Verify update_session was never called
    mock_cache.update_session.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_initial_sessions_empty_computers():
    """Test _pull_initial_sessions handles empty computer list."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    mock_cache.get_computers.return_value = []
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock()

    # Execute
    await adapter._pull_initial_sessions()

    # Verify no requests were made
    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_happy_path():
    """Test pull_remote_projects successfully pulls projects from remote."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-456")
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": [
                    {"name": "ProjectA", "path": "/home/user/projectA", "desc": "Project A"},
                    {"name": "ProjectB", "path": "/home/user/projectB", "desc": "Project B"},
                ],
            }
        )
    )

    # Execute
    await adapter.pull_remote_projects("RemotePC")

    # Verify cache was populated
    mock_cache.apply_projects_snapshot.assert_called_once()
    call_args = mock_cache.apply_projects_snapshot.call_args
    assert call_args[0][0] == "RemotePC"
    assert len(call_args[0][1]) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_no_cache():
    """Test pull_remote_projects skips when cache is unavailable."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = None
    adapter.send_request = AsyncMock()

    # Execute
    await adapter.pull_remote_projects("RemotePC")

    # Verify no requests were made
    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_timeout():
    """Test pull_remote_projects handles timeout gracefully."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-456")
    mock_client.read_response = AsyncMock(side_effect=TimeoutError("timeout"))

    # Execute (should not crash)
    await adapter.pull_remote_projects("RemotePC")

    # Verify cache was not populated
    mock_cache.set_projects.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_todos_happy_path():
    """Test pull_remote_todos successfully pulls todos from remote."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-789")
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": [
                    {"slug": "todo-1", "title": "Todo 1", "status": "pending"},
                    {"slug": "todo-2", "title": "Todo 2", "status": "complete"},
                ],
            }
        )
    )

    # Execute
    await adapter.pull_remote_todos("RemotePC", "/home/user/project")

    # Verify cache was populated
    mock_cache.set_todos.assert_called_once()
    call_args = mock_cache.set_todos.call_args
    assert call_args[0][0] == "RemotePC"
    assert call_args[0][1] == "/home/user/project"
    assert len(call_args[0][2]) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_todos_no_cache():
    """Test pull_remote_todos skips when cache is unavailable."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = None
    adapter.send_request = AsyncMock()

    # Execute
    await adapter.pull_remote_todos("RemotePC", "/home/user/project")

    # Verify no requests were made
    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_with_todos_happy_path():
    """Test pull_remote_projects_with_todos pulls projects and todos from remote."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    adapter.send_request = AsyncMock(return_value="msg-900")
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": [
                    {
                        "name": "ProjectA",
                        "path": "/home/user/projectA",
                        "desc": "Project A",
                        "todos": [
                            {"slug": "todo-1", "title": "Todo 1", "status": "pending"},
                        ],
                    },
                    {
                        "name": "ProjectB",
                        "path": "/home/user/projectB",
                        "desc": "Project B",
                        "todos": [],
                    },
                ],
            }
        )
    )

    await adapter.pull_remote_projects_with_todos("RemotePC")

    mock_cache.apply_projects_snapshot.assert_called_once()
    mock_cache.apply_todos_snapshot.assert_called_once()
    todos_call = mock_cache.apply_todos_snapshot.call_args
    assert todos_call[0][0] == "RemotePC"
    todos_by_project = todos_call[0][1]
    assert "/home/user/projectA" in todos_by_project
    assert "/home/user/projectB" in todos_by_project


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_with_todos_no_cache():
    """Test pull_remote_projects_with_todos skips when cache is unavailable."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = None
    adapter.send_request = AsyncMock()

    await adapter.pull_remote_projects_with_todos("RemotePC")

    adapter.send_request.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pull_remote_projects_with_todos_fallbacks_to_projects():
    """Fallback to list_projects when projects-with-todos is unsupported."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = MagicMock()

    adapter.send_request = AsyncMock(return_value="msg-901")
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "error",
                "error": "No handler registered for event: list_projects_with_todos",
            }
        )
    )
    adapter.pull_remote_projects = AsyncMock()

    await adapter.pull_remote_projects_with_todos("RemotePC")

    adapter.pull_remote_projects.assert_awaited_once_with("RemotePC")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_populates_cache():
    """Test that heartbeat processing populates cache with computer info."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    # Mock Redis heartbeat scan
    mock_redis = AsyncMock()
    mock_redis.scan = AsyncMock(return_value=(0, [b"computer:RemotePC:heartbeat"]))
    mock_redis.get = AsyncMock(
        return_value=json.dumps(
            {
                "computer_name": "RemotePC",
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "interested_in": [],
            }
        ).encode("utf-8")
    )
    adapter.redis = mock_redis

    # Execute
    await adapter._get_interested_computers("sessions")

    # Verify cache was updated
    mock_cache.update_computer.assert_called_once()
    call_args = mock_cache.update_computer.call_args
    assert call_args[0][0].name == "RemotePC"
    assert call_args[0][0].status == "online"
