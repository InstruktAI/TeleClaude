"""Unit tests for teleclaude__send_result MCP tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_mcp_server():
    """Create MCP server with mocked dependencies."""
    from teleclaude.mcp_server import TeleClaudeMCPServer

    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value="msg-123")

    mock_terminal_bridge = MagicMock()

    with patch("teleclaude.mcp_server.config") as mock_config:
        mock_config.computer.name = "TestComputer"
        server = TeleClaudeMCPServer(adapter_client=mock_client, terminal_bridge=mock_terminal_bridge)

    return server


@pytest.mark.asyncio
async def test_send_result_with_valid_content(mock_mcp_server):
    """Test sending result with valid markdown content."""
    server = mock_mcp_server

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await server.teleclaude__send_result("test-session-123", "# Test Result\n\nSome content")

    assert result["status"] == "success"
    assert result["message_id"] == "msg-123"
    server.client.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_result_with_empty_content(mock_mcp_server):
    """Test that empty content returns error."""
    server = mock_mcp_server

    result = await server.teleclaude__send_result("test-session-123", "")

    assert result["status"] == "error"
    assert "empty" in result["message"].lower()
    server.client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_result_with_whitespace_only_content(mock_mcp_server):
    """Test that whitespace-only content returns error."""
    server = mock_mcp_server

    result = await server.teleclaude__send_result("test-session-123", "   \n\n   ")

    assert result["status"] == "error"
    assert "empty" in result["message"].lower()


@pytest.mark.asyncio
async def test_send_result_with_missing_session(mock_mcp_server):
    """Test that missing session returns error."""
    server = mock_mcp_server

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        result = await server.teleclaude__send_result("nonexistent-session", "Some content")

    assert result["status"] == "error"
    assert "not found" in result["message"].lower()


@pytest.mark.asyncio
async def test_send_result_strips_outer_codeblock(mock_mcp_server):
    """Test that outer code block is stripped and re-wrapped with md."""
    server = mock_mcp_server

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        # Content wrapped in code block
        await server.teleclaude__send_result("test-session-123", "```\nActual content\n```")

    # Check that send_message was called with re-wrapped content
    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    assert "Actual content" in sent_text
    # Should be wrapped in ```md ... ```
    assert sent_text.startswith("```md")
    assert sent_text.endswith("```")


@pytest.mark.asyncio
async def test_send_result_wraps_content_in_markdown_codeblock(mock_mcp_server):
    """Test that content is wrapped in ```md code block."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        await server.teleclaude__send_result("test-session-123", "# Title\n\nSome content")

    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    # Content should be wrapped in markdown code block
    assert sent_text.startswith("```md\n")
    assert sent_text.endswith("\n```")
    assert "# Title" in sent_text


@pytest.mark.asyncio
async def test_send_result_applies_markdown_escaping(mock_mcp_server):
    """Test that MarkdownV2 escaping is applied outside code blocks."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        await server.teleclaude__send_result("test-session-123", "Text with . and !")

    # Check that send_message was called with content in code block
    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    # Content is inside code block, so special chars should NOT be escaped
    assert "```md" in sent_text
    assert "Text with . and !" in sent_text


@pytest.mark.asyncio
async def test_send_result_truncates_long_content(mock_mcp_server):
    """Test that content longer than 4096 chars is truncated."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        # Create content longer than 4096 characters
        long_content = "A" * 5000
        await server.teleclaude__send_result("test-session-123", long_content)

    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    assert len(sent_text) <= 4096
    assert sent_text.endswith("...")


@pytest.mark.asyncio
async def test_send_result_uses_markdownv2_parse_mode(mock_mcp_server):
    """Test that MarkdownV2 parse mode is used."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        await server.teleclaude__send_result("test-session-123", "Test content")

    call_args = server.client.send_message.call_args
    metadata = call_args.kwargs["metadata"]
    assert metadata.parse_mode == "MarkdownV2"


@pytest.mark.asyncio
async def test_send_result_fallback_to_plain_text_on_markdown_error(mock_mcp_server):
    """Test fallback to plain text if MarkdownV2 fails."""
    server = mock_mcp_server

    mock_session = MagicMock()

    # First call raises exception (MarkdownV2 parse error), second succeeds (plain text)
    server.client.send_message = AsyncMock(side_effect=[Exception("Parse error"), "msg-456"])

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await server.teleclaude__send_result("test-session-123", "Test content")

    assert result["status"] == "success"
    assert result["message_id"] == "msg-456"
    assert "warning" in result
    # Should have been called twice: once for MarkdownV2, once for plain text
    assert server.client.send_message.call_count == 2


@pytest.mark.asyncio
async def test_send_result_error_on_complete_failure(mock_mcp_server):
    """Test error response if both MarkdownV2 and plain text fail."""
    server = mock_mcp_server

    mock_session = MagicMock()

    # Both calls fail
    server.client.send_message = AsyncMock(side_effect=Exception("Network error"))

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await server.teleclaude__send_result("test-session-123", "Test content")

    assert result["status"] == "error"
    assert "Network error" in result["message"]
