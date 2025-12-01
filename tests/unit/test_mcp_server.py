"""Unit tests for MCP server tools."""

import pytest


@pytest.mark.skip(reason="TODO: Implement test")
async def test_teleclaude_list_computers_returns_online_computers():
    """Test that list_computers returns online computers from heartbeat.

    TODO: Test computer listing:
    - Mock redis_adapter.discover_peers
    - Verify returned format
    - Verify filtering (online only)
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_teleclaude_list_sessions_formats_sessions():
    """Test that list_sessions formats session data for MCP.

    TODO: Test session listing:
    - Mock db.list_sessions
    - Verify JSON format
    - Verify required fields present
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_teleclaude_start_session_creates_session():
    """Test that start_session creates a new session.

    TODO: Test session creation:
    - Mock command_handlers.handle_create_session
    - Verify session_id returned
    - Verify metadata passed correctly
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_teleclaude_send_message_forwards_to_handler():
    """Test that send_message forwards to command handler.

    TODO: Test message forwarding:
    - Mock command_handlers.handle_message
    - Verify message sent to correct session
    - Verify error handling (session not found)
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_teleclaude_send_notification_sends_to_session():
    """Test that send_notification sends notification message.

    TODO: Test notification:
    - Mock adapter_client.send_message
    - Verify notification format
    - Test with invalid session_id
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_teleclaude_send_file_handles_upload():
    """Test that send_file uploads file to session.

    TODO: Test file upload:
    - Mock file_handler.handle_file
    - Verify file path validation
    - Test with non-existent file
    - Test with no active process
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_teleclaude_get_session_data_formats_transcript():
    """Test that get_session_data returns formatted transcript.

    TODO: Test data retrieval:
    - Mock output file reading
    - Mock db.get_session
    - Verify transcript formatting
    - Verify metadata included
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_teleclaude_download_session_strips_markers():
    """Test that download_session strips exit markers from output.

    TODO: Test download:
    - Create sample output with markers
    - Verify markers removed
    - Verify clean transcript returned
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_mcp_tools_handle_invalid_session_id():
    """Test that MCP tools handle invalid session_id gracefully.

    TODO: Test error handling:
    - Test each tool with non-existent session_id
    - Verify error messages
    - Verify no crashes
    """
