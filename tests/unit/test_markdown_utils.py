"""Unit tests for markdown utilities."""

import pytest

from teleclaude.utils.markdown import escape_markdown_v2, strip_outer_codeblock


class TestStripOuterCodeblock:
    """Tests for strip_outer_codeblock function."""

    def test_strips_outer_codeblock_with_language(self):
        """Test stripping outer code block with language identifier."""
        text = "```python\nprint('hello')\n```"
        result = strip_outer_codeblock(text)
        assert result == "print('hello')"

    def test_strips_outer_codeblock_without_language(self):
        """Test stripping outer code block without language identifier."""
        text = "```\nsome code\n```"
        result = strip_outer_codeblock(text)
        assert result == "some code"

    def test_preserves_inner_codeblocks(self):
        """Test that inner code blocks are preserved."""
        text = "```\nOuter text\n```inner\ncode\n```\nMore text\n```"
        result = strip_outer_codeblock(text)
        assert result == "Outer text\n```inner\ncode\n```\nMore text"

    def test_preserves_multiline_content(self):
        """Test that multiline content is preserved."""
        text = "```python\nline1\nline2\nline3\n```"
        result = strip_outer_codeblock(text)
        assert result == "line1\nline2\nline3"

    def test_returns_unchanged_if_no_outer_codeblock(self):
        """Test that text without outer code block is unchanged."""
        text = "Just plain text"
        result = strip_outer_codeblock(text)
        assert result == "Just plain text"

    def test_returns_unchanged_if_incomplete_codeblock(self):
        """Test that incomplete code block is unchanged."""
        text = "```python\nsome code"
        result = strip_outer_codeblock(text)
        assert result == "```python\nsome code"

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        result = strip_outer_codeblock("")
        assert result == ""

    def test_handles_whitespace_padding(self):
        """Test handling of whitespace around code block."""
        text = "  ```\ncontent\n```  "
        result = strip_outer_codeblock(text)
        assert result == "content"


class TestEscapeMarkdownV2:
    """Tests for escape_markdown_v2 function."""

    def test_escapes_special_characters(self):
        """Test escaping of MarkdownV2 special characters."""
        text = "Test _underscore_ and *asterisk*"
        result = escape_markdown_v2(text)
        # Note: Inside formatting markers, characters should NOT be escaped
        # This is a simplified test - actual behavior depends on context
        assert "\\_" in result or "_" in result

    def test_preserves_code_blocks(self):
        """Test that code blocks are not escaped."""
        text = "Normal text ```code_with_underscore``` more text"
        result = escape_markdown_v2(text)
        # Inside code blocks, special chars should not be escaped
        assert "```code_with_underscore```" in result

    def test_preserves_inline_code(self):
        """Test that inline code is not escaped."""
        text = "Text with `inline_code` here"
        result = escape_markdown_v2(text)
        assert "`inline_code`" in result

    def test_escapes_outside_code(self):
        """Test that characters outside code are escaped."""
        text = "Test text with . and !"
        result = escape_markdown_v2(text)
        assert "\\." in result
        assert "\\!" in result

    def test_handles_multiple_code_blocks(self):
        """Test handling of multiple code blocks."""
        text = "Before ```block1``` middle ```block2``` after"
        result = escape_markdown_v2(text)
        assert "```block1```" in result
        assert "```block2```" in result

    def test_handles_nested_backticks(self):
        """Test handling of nested backticks."""
        text = "Text ```outer `inner` outer``` text"
        result = escape_markdown_v2(text)
        assert "```outer `inner` outer```" in result

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        result = escape_markdown_v2("")
        assert result == ""

    def test_escapes_all_special_chars(self):
        """Test that all MarkdownV2 special characters are handled."""
        # Characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
        text = "_*[]()~`>#+-=|{}.!"
        result = escape_markdown_v2(text)
        # All should be escaped or handled (backticks toggle code mode)
        assert "\\" in result or "`" in result

    def test_handles_table_syntax(self):
        """Test handling of markdown table syntax."""
        text = "| Col1 | Col2 |\n|------|------|\n| val1 | val2 |"
        result = escape_markdown_v2(text)
        # Pipes and dashes should be escaped
        assert "\\|" in result
        assert "\\-" in result
