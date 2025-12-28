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
async def test_send_result_converts_bold_to_telegram_format(mock_mcp_server):
    """Test that GitHub-style bold (**text**) is converted to Telegram (*text*)."""
    server = mock_mcp_server

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        await server.teleclaude__send_result("test-session-123", "**bold text**")

    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    # telegramify-markdown converts **bold** to *bold*
    assert "*bold text*" in sent_text
    assert "**" not in sent_text


@pytest.mark.asyncio
async def test_send_result_converts_headers(mock_mcp_server):
    """Test that headers are converted to Telegram format."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        await server.teleclaude__send_result("test-session-123", "# Header Title")

    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    # telegramify-markdown converts headers to bold with emoji prefix
    assert "Header Title" in sent_text
    # Header should be bold (starts with *)
    assert "*" in sent_text


@pytest.mark.asyncio
async def test_send_result_adds_md_language_to_plain_code_blocks(mock_mcp_server):
    """Test that plain code blocks get 'md' language added."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        # Tables get wrapped in plain ``` by the library
        await server.teleclaude__send_result("test-session-123", "| A | B |\n|---|---|\n| 1 | 2 |")

    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    # Plain code blocks should have 'md' language added
    assert "```md\n" in sent_text
    # Should not have plain ``` without language
    assert "\n```\n" not in sent_text or sent_text.count("```") == 2  # opening and closing only


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


@pytest.mark.asyncio
async def test_send_result_handles_nested_backticks_in_code_blocks(mock_mcp_server):
    """Test that nested ``` inside code blocks are properly escaped."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        # Content with nested code block example
        content = "Here's a code example:\n```python\nprint('```')\n```"
        await server.teleclaude__send_result("test-session-123", content)

    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    # Library escapes backticks inside code blocks as \` - verify they're escaped
    # The raw ``` should NOT appear inside the code block (would break markdown)
    # Instead it should be escaped as \`\`\` or `\u200b``
    assert "print" in sent_text
    # The triple backtick inside should be escaped (not raw)
    code_block_content = sent_text.split("```python\n")[1].split("\n```")[0]
    # Should not have raw unescaped ``` inside the code block
    assert "```" not in code_block_content or "\\`" in code_block_content or "\u200b" in code_block_content


@pytest.mark.asyncio
async def test_send_result_html_mode_uses_html_parse_mode(mock_mcp_server):
    """Test that HTML output_format uses HTML parse mode without conversion."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        # HTML content with link
        content = '<a href="message://test">Click me</a>'
        await server.teleclaude__send_result("test-session-123", content, "html")

    call_args = server.client.send_message.call_args
    sent_text = call_args.kwargs["text"]
    metadata = call_args.kwargs["metadata"]
    # HTML content should be sent as-is
    assert sent_text == content
    # Parse mode should be HTML
    assert metadata.parse_mode == "HTML"


@pytest.mark.asyncio
async def test_send_result_default_output_format_is_markdown(mock_mcp_server):
    """Test that default output_format uses MarkdownV2."""
    server = mock_mcp_server

    mock_session = MagicMock()

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        # Call without output_format - should default to markdown
        await server.teleclaude__send_result("test-session-123", "**bold**")

    call_args = server.client.send_message.call_args
    metadata = call_args.kwargs["metadata"]
    assert metadata.parse_mode == "MarkdownV2"
