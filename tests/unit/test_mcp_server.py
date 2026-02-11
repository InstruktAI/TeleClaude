"""Unit tests for MCP server tools."""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.models import ComputerInfo, SessionSummary, ThinkingMode
from teleclaude.mcp_server import MCP_SESSION_DATA_MAX_CHARS, TeleClaudeMCPServer
from teleclaude.types.commands import CloseSessionCommand

CALLER_SESSION_ID = "caller-session-123"

# System boundary: MCP tools dispatch events to the adapter client. Payload assertions verify this boundary.


@pytest.fixture
def mock_mcp_server():
    """Create MCP server with mocked dependencies."""
    mock_client = MagicMock()
    mock_client.discover_peers = AsyncMock(return_value=[])
    mock_commands = MagicMock()
    mock_commands.create_session = AsyncMock(return_value={"session_id": "test-session-123"})
    mock_commands.start_agent = AsyncMock()
    mock_commands.process_message = AsyncMock()
    mock_commands.end_session = AsyncMock(return_value={"status": "success"})
    mock_commands.get_session_data = AsyncMock(return_value={"status": "success", "messages": ""})

    mock_tmux_bridge = MagicMock()

    # Mock caller session for db.get_session
    mock_caller_session = MagicMock()
    mock_caller_session.active_agent = "claude"
    mock_caller_session.thinking_mode = "slow"
    mock_caller_session.last_input_origin = "telegram"

    with (
        patch("teleclaude.mcp_server.config") as mock_config,
        patch("teleclaude.mcp.handlers.db.get_session", new=AsyncMock(return_value=mock_caller_session)),
        patch("teleclaude.mcp.handlers.get_command_service", return_value=mock_commands),
    ):
        mock_config.computer.name = "TestComputer"
        mock_config.mcp.socket_path = "/tmp/test.sock"

        server = TeleClaudeMCPServer(adapter_client=mock_client, tmux_bridge=mock_tmux_bridge)
        server.command_service = mock_commands

        yield server


@pytest.mark.asyncio
async def test_teleclaude_list_computers_returns_online_computers(mock_mcp_server):
    """Test that list_computers returns online computers from heartbeat."""
    server = mock_mcp_server

    # Mock get_computer_info for local computer
    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.get_computer_info = AsyncMock(
            return_value=ComputerInfo(
                name="TestComputer",
                status="online",
                user="testuser",
                host="localhost",
                role="development",
                is_local=True,
                system_stats={"memory": {"percent_used": 50.0}},
            )
        )

        # Mock discover_peers to return remote peers
        server.client.discover_peers = AsyncMock(
            return_value=[
                {
                    "name": "RemotePC",
                    "status": "online",
                    "last_seen": datetime.now(timezone.utc),
                    "user": "remoteuser",
                    "host": "remote.local",
                }
            ]
        )

        result = await server.teleclaude__list_computers()

        assert len(result) == 2
        # First is local computer
        assert result[0]["name"] == "TestComputer"
        assert result[0]["status"] == "local"
        # Second is remote
        assert result[1]["name"] == "RemotePC"
        assert result[1]["status"] == "online"


@pytest.mark.asyncio
async def test_teleclaude_list_sessions_formats_sessions(mock_mcp_server):
    """Test that list_sessions formats session data for MCP."""
    server = mock_mcp_server

    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.list_sessions = AsyncMock(
            return_value=[
                SessionSummary(
                    session_id="test-session-123",
                    last_input_origin=InputOrigin.TELEGRAM.value,
                    title="Test Session",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                )
            ]
        )

        result = await server.teleclaude__list_sessions(computer="local")

        assert len(result) == 1
        assert result[0]["session_id"] == "test-session-123"
        assert result[0]["last_input_origin"] == "telegram"
        assert result[0]["computer"] == "TestComputer"


@pytest.mark.asyncio
async def test_teleclaude_end_session_wraps_close_command(mock_mcp_server):
    """Local end_session should wrap session_id into CloseSessionCommand."""
    server = mock_mcp_server
    captured = {}

    async def fake_end_session(cmd, _client):
        captured["cmd"] = cmd
        return {"status": "success", "message": "ok"}

    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.end_session = AsyncMock(side_effect=fake_end_session)

        result = await server.teleclaude__end_session(computer="local", session_id="sess-1")

    assert result["status"] == "success"
    assert isinstance(captured["cmd"], CloseSessionCommand)
    assert captured["cmd"].session_id == "sess-1"


@pytest.mark.asyncio
async def test_teleclaude_list_sessions_filters_by_caller(mock_mcp_server):
    """Test that list_sessions returns sessions spawned by the caller."""
    server = mock_mcp_server

    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.list_sessions = AsyncMock(
            return_value=[
                SessionSummary(
                    session_id="sess-1",
                    last_input_origin=InputOrigin.TELEGRAM.value,
                    title="Session One",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                    initiator_session_id="caller-1",
                ),
                SessionSummary(
                    session_id="sess-2",
                    last_input_origin=InputOrigin.TELEGRAM.value,
                    title="Session Two",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                    initiator_session_id="caller-2",
                ),
                SessionSummary(
                    session_id="sess-3",
                    last_input_origin=InputOrigin.TELEGRAM.value,
                    title="Session Three",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                    initiator_session_id=None,
                ),
            ]
        )

        result = await server.teleclaude__list_sessions(
            computer="local",
            caller_session_id="caller-1",
        )

        assert [session["session_id"] for session in result] == ["sess-1"]


@pytest.mark.asyncio
async def test_teleclaude_list_sessions_without_caller_returns_unfiltered(mock_mcp_server):
    """Test that list_sessions returns unfiltered sessions when caller is unknown."""
    server = mock_mcp_server

    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.list_sessions = AsyncMock(
            return_value=[
                SessionSummary(
                    session_id="sess-1",
                    last_input_origin=InputOrigin.TELEGRAM.value,
                    title="Session One",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                    initiator_session_id="caller-1",
                ),
                SessionSummary(
                    session_id="sess-2",
                    last_input_origin=InputOrigin.TELEGRAM.value,
                    title="Session Two",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                    initiator_session_id="caller-2",
                ),
            ]
        )

        result = await server.teleclaude__list_sessions(
            computer="local",
            caller_session_id=None,
        )

        assert [session["session_id"] for session in result] == ["sess-1", "sess-2"]


@pytest.mark.asyncio
async def test_teleclaude_list_sessions_isolates_multiple_callers(mock_mcp_server):
    """Test that list_sessions isolates sessions per orchestrator."""
    server = mock_mcp_server

    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.list_sessions = AsyncMock(
            return_value=[
                SessionSummary(
                    session_id="sess-1",
                    last_input_origin=InputOrigin.TELEGRAM.value,
                    title="Session One",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                    initiator_session_id="caller-1",
                ),
                SessionSummary(
                    session_id="sess-2",
                    last_input_origin=InputOrigin.TELEGRAM.value,
                    title="Session Two",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                    initiator_session_id="caller-2",
                ),
            ]
        )

        caller_one = await server.teleclaude__list_sessions(
            computer="local",
            caller_session_id="caller-1",
        )
        caller_two = await server.teleclaude__list_sessions(
            computer="local",
            caller_session_id="caller-2",
        )

        assert [session["session_id"] for session in caller_one] == ["sess-1"]
        assert [session["session_id"] for session in caller_two] == ["sess-2"]


@pytest.mark.asyncio
async def test_teleclaude_start_session_creates_session(mock_mcp_server):
    """Test that start_session creates a new session."""
    server = mock_mcp_server

    # Mock create_session to return success with session_id
    server.command_service.create_session = AsyncMock(return_value={"session_id": "new-session-456"})

    with patch(
        "teleclaude.mcp.handlers.db.get_session",
        new=AsyncMock(return_value=MagicMock(last_input_origin=InputOrigin.TELEGRAM.value)),
    ):
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Test Session",
            message="Hello Claude",
            caller_session_id=CALLER_SESSION_ID,
        )

        assert result["status"] == "success"
    assert result["session_id"] == "new-session-456"


@pytest.mark.asyncio
async def test_teleclaude_send_message_forwards_to_handler(mock_mcp_server):
    """Test that send_message forwards to command handler."""
    server = mock_mcp_server

    server.command_service.process_message = AsyncMock(return_value=None)

    chunks = []
    async for chunk in server.teleclaude__send_message(
        computer="local",
        session_id="test-session-123",
        message="ls -la",
        caller_session_id=CALLER_SESSION_ID,
    ):
        chunks.append(chunk)

    result = "".join(chunks)
    assert "Message sent" in result
    assert "test-ses" in result  # First 8 chars of session_id


@pytest.mark.asyncio
async def test_teleclaude_send_file_handles_upload(mock_mcp_server):
    """Test that send_file uploads file to session."""
    import tempfile

    server = mock_mcp_server

    # Create temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Test content")
        test_file = f.name

    try:
        # Mock db.get_session
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"

        with patch("teleclaude.mcp.handlers.db.get_session", new=AsyncMock(return_value=mock_session)):
            server.client.send_file = AsyncMock(return_value="file-msg-123")

            result = await server.teleclaude__send_file(
                session_id="test-session-123",
                file_path=test_file,
                caption="Test caption",
            )

            assert "File sent successfully" in result
            assert "file-msg-123" in result
    finally:
        Path(test_file).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_teleclaude_get_session_data_formats_transcript(mock_mcp_server):
    """Test that get_session_data returns transcript summary."""
    server = mock_mcp_server

    server.command_service.get_session_data = AsyncMock(
        return_value={
            "status": "success",
            "session_id": "test-session-123",
            "messages": "Parsed transcript content",
        }
    )

    result = await server.teleclaude__get_session_data(
        computer="local",
        session_id="test-session-123",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    assert result["messages"] == "Parsed transcript content"


@pytest.mark.asyncio
async def test_teleclaude_get_session_data_caps_large_transcripts(mock_mcp_server):
    """Test that large transcripts are capped to protect transport."""
    server = mock_mcp_server

    # Create large transcript (> 48KB)
    large_transcript = "A" * (MCP_SESSION_DATA_MAX_CHARS + 1000)

    server.command_service.get_session_data = AsyncMock(
        return_value={
            "status": "success",
            "session_id": "test-session-123",
            "messages": large_transcript,
        }
    )

    result = await server.teleclaude__get_session_data(
        computer="local",
        session_id="test-session-123",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    assert len(result["messages"]) <= MCP_SESSION_DATA_MAX_CHARS
    assert result["truncated"] is True
    assert "Response capped" in result["cap_notice"]


@pytest.mark.asyncio
async def test_teleclaude_send_file_validates_file_path(mock_mcp_server):
    """Test that send_file rejects invalid paths."""
    server = mock_mcp_server

    # Non-existent file
    result = await server.teleclaude__send_file(
        session_id="test-session-123",
        file_path="/nonexistent/file.txt",
    )
    assert "Error: File not found" in result

    # Directory instead of file
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await server.teleclaude__send_file(
            session_id="test-session-123",
            file_path=tmpdir,
        )
        assert "Error: Not a file" in result


@pytest.mark.asyncio
async def test_mcp_tools_handle_invalid_session_id(mock_mcp_server):
    """Test that tools return errors for missing sessions."""
    server = mock_mcp_server

    # Mock db.get_session to return None
    with patch("teleclaude.mcp.handlers.db.get_session", new=AsyncMock(return_value=None)):
        # Use an existing path (the test file itself)
        existing_path = __file__

        # test send_file
        result = await server.teleclaude__send_file(
            session_id="missing-sess",
            file_path=existing_path,
        )
        assert "Error: Session missing-sess not found" in result


@pytest.mark.asyncio
async def test_teleclaude_start_session_with_agent_parameter(mock_mcp_server):
    """Test that start_session dispatches correct agent event based on parameter."""
    server = mock_mcp_server

    async def mock_create_session(cmd):
        sid = "agent-test-123"
        if "Gemini" in cmd.title:
            sid = "agent-test-123"
        elif "Codex" in cmd.title:
            sid = "agent-test-456"
        elif "Claude" in cmd.title:
            sid = "agent-test-789"
        if "Fast" in cmd.title:
            sid = "agent-test-fast"
        return {"session_id": sid}

    server.command_service.create_session = AsyncMock(side_effect=mock_create_session)

    with patch(
        "teleclaude.mcp.handlers.db.get_session",
        new=AsyncMock(return_value=MagicMock(last_input_origin=InputOrigin.TELEGRAM.value)),
    ):
        # Test 1: Gemini agent
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Gemini Session",
            message="Hello Gemini",
            agent="gemini",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        assert result["session_id"] == "agent-test-123"

        # Test 2: Codex agent
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Codex Session",
            message="Hello Codex",
            agent="codex",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        assert result["session_id"] == "agent-test-456"

        # Test 3: Claude agent (default)
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Claude Session",
            message="Hello Claude",
            agent="claude",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        assert result["session_id"] == "agent-test-789"

        # Test explicit fast mode
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Fast Claude Session",
            message="Hello Claude",
            agent="claude",
            thinking_mode=ThinkingMode.FAST,
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        assert result["session_id"] == "agent-test-fast"


@pytest.mark.asyncio
async def test_run_agent_command_passes_mode_for_new_session(mock_mcp_server):
    """Test that run_agent_command passes thinking_mode for new sessions."""
    server = mock_mcp_server
    server.command_service.create_session = AsyncMock(return_value={"session_id": "sess-123"})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="/next-work",
        args="",
        project="/home/user/project",
        agent="codex",
        thinking_mode=ThinkingMode.MED,
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    call_args = server.command_service.create_session.call_args
    cmd = call_args.args[0]
    assert "codex" in cmd.auto_command
    assert "med" in cmd.auto_command


@pytest.mark.asyncio
async def test_run_agent_command_rejects_without_slash(mock_mcp_server):
    """Test that run_agent_command rejects commands without leading /."""
    server = mock_mcp_server

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        project="/home/user/project",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "error"
    assert "must start with '/'" in result["message"]


# --- run_agent_command tests ---


@pytest.mark.asyncio
async def test_run_agent_command_starts_new_session(mock_mcp_server):
    """Test that run_agent_command creates a new session."""
    server = mock_mcp_server
    server.command_service.create_session = AsyncMock(return_value={"session_id": "new-session-789"})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="/next-work",
        project="/home/user/project",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    assert result["session_id"] == "new-session-789"


@pytest.mark.asyncio
async def test_run_agent_command_requires_project(mock_mcp_server):
    """Test that run_agent_command returns error if project missing."""
    server = mock_mcp_server

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="/next-work",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "error"
    assert "project required" in result["message"]


@pytest.mark.asyncio
async def test_run_agent_command_with_subfolder(mock_mcp_server):
    """Test that run_agent_command passes subfolder to new session."""
    server = mock_mcp_server
    server.command_service.create_session = AsyncMock(return_value={"session_id": "sess-sub"})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="/next-work",
        project="/home/user/project",
        subfolder="worktrees/feat",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    call_args = server.command_service.create_session.call_args_list[0]
    cmd = call_args.args[0]
    assert cmd.subdir == "worktrees/feat"


@pytest.mark.asyncio
async def test_run_agent_command_with_agent_type(mock_mcp_server):
    """Test that run_agent_command uses specified agent."""
    server = mock_mcp_server
    server.command_service.create_session = AsyncMock(return_value={"session_id": "sess-agent"})

    await server.teleclaude__run_agent_command(
        computer="local",
        command="/next-work",
        project="/home/user/project",
        agent="gemini",
        caller_session_id=CALLER_SESSION_ID,
    )

    call_args = server.command_service.create_session.call_args
    cmd = call_args.args[0]
    assert "gemini" in cmd.auto_command


@pytest.mark.asyncio
async def test_run_agent_command_codex_uses_normalized_command(mock_mcp_server):
    """Test that codex commands use normalized /next-* command names."""
    server = mock_mcp_server
    server.command_service.create_session = AsyncMock(return_value={"session_id": "sess-codex"})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="/next-work",
        project="/home/user/project",
        agent="codex",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    call_args = server.command_service.create_session.call_args
    cmd = call_args.args[0]
    assert "/next-work" in cmd.auto_command
    assert "prompts:next-work" not in cmd.auto_command


@pytest.mark.asyncio
async def test_run_agent_command_with_args(mock_mcp_server):
    """Test that run_agent_command appends args to command."""
    server = mock_mcp_server
    server.command_service.create_session = AsyncMock(return_value={"session_id": "sess-args"})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="/next-work",
        args="my-feature",
        project="/home/user/project",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    call_args = server.command_service.create_session.call_args
    cmd = call_args.args[0]
    assert "my-feature" in cmd.title


@pytest.mark.asyncio
async def test_mark_phase_schema_allows_pending(mock_mcp_server):
    """Test that mark_phase accepts 'pending' status."""
    server = mock_mcp_server

    with (
        patch("teleclaude.mcp.handlers.mark_phase") as mock_mark,
        patch("teleclaude.mcp.handlers.Path.exists", return_value=True),
        patch("teleclaude.mcp.handlers.has_uncommitted_changes", return_value=False),
    ):
        calls = []

        def record_mark(*args, **kwargs):
            calls.append((args, kwargs))
            return "pending"

        mock_mark.side_effect = record_mark

        result = await server.teleclaude__mark_phase(
            slug="test-slug",
            phase="build",
            status="pending",
            cwd="/home/user/project",
        )

        assert "state updated" in result
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_mark_phase_blocks_on_uncommitted_changes(mock_mcp_server):
    """Test that mark_phase returns error if there are uncommitted changes."""
    server = mock_mcp_server

    with (
        patch("teleclaude.mcp.handlers.has_uncommitted_changes", return_value=True),
        patch("teleclaude.mcp.handlers.Path.exists", return_value=True),
    ):
        result = await server.teleclaude__mark_phase(
            slug="test-slug",
            phase="build",
            status="complete",
            cwd="/home/user/project",
        )

        assert "UNCOMMITTED_CHANGES" in result
        assert "stash" not in result.lower()


@pytest.mark.asyncio
async def test_mark_phase_blocks_on_stash_debt(mock_mcp_server):
    """mark_phase should hard-stop when repository stash is non-empty."""
    server = mock_mcp_server

    with (
        patch("teleclaude.mcp.handlers.has_uncommitted_changes", return_value=False),
        patch("teleclaude.mcp.handlers.get_stash_entries", return_value=["stash@{0}: WIP on foo"]),
        patch("teleclaude.mcp.handlers.Path.exists", return_value=True),
    ):
        result = await server.teleclaude__mark_phase(
            slug="test-slug",
            phase="build",
            status="complete",
            cwd="/home/user/project",
        )

    assert "STASH_DEBT" in result
