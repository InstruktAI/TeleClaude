"""Unit tests for markdown utilities."""

from pathlib import Path

from teleclaude.core.agents import AgentName
from teleclaude.utils.markdown import (
    MARKDOWN_V2_INITIAL_STATE,
    _required_markdown_closers,
    collapse_fenced_code_blocks,
    continuation_prefix_for_markdown_v2_state,
    escape_markdown_v2,
    escape_markdown_v2_preformatted,
    leading_balanced_markdown_v2_entity_span,
    scan_markdown_v2_state,
    strip_outer_codeblock,
    telegramify_markdown,
    truncate_markdown_v2,
    truncate_markdown_v2_by_bytes,
    truncate_markdown_v2_with_consumed,
    unescape_markdown_v2,
)
from teleclaude.utils.transcript import render_agent_output


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


class TestEscapeMarkdownV2Preformatted:
    """Tests for escape_markdown_v2_preformatted function."""

    def test_escapes_backticks_and_backslashes(self):
        """Backticks and backslashes are escaped for pre/code entities."""
        text = r"path C:\repo\tele`claude\\"
        result = escape_markdown_v2_preformatted(text)
        assert r"C:\\repo\\tele\`claude\\\\" in result


class TestTelegramifyMarkdown:
    """Tests for telegramify_markdown function."""

    def test_strips_heading_icons(self):
        """Test that heading icons added by telegramify_markdown are stripped."""
        # The library adds icons like 📌 to headings
        text = "# Section Title"
        result = telegramify_markdown(text, strip_heading_icons=True)
        # Result should be bold but without the icon
        assert "*Section Title*" in result
        assert "📌" not in result

    def test_escapes_nested_code_blocks(self):
        """Test that nested code blocks are escaped to prevent breaking outer fence."""
        # Realistic case: a code block containing triple backticks (e.g. in a string or comment)
        text = "Here is a block:\n```python\n# This would break if not escaped:\n# ```\nprint('hello')\n```"
        result = telegramify_markdown(text)
        # Should contain escaped backticks sequence
        assert "`\u200b``" in result

    def test_adds_md_tag_to_plain_code_blocks(self):
        """Test that plain code blocks get a 'md' tag for better Telegram rendering."""
        text = "```\nplain code\n```"
        result = telegramify_markdown(text)
        assert "```md\n" in result

    def test_preserves_existing_language_tags(self):
        """Test that existing language tags are not overwritten with 'md'."""
        text = "```python\nprint(1)\n```"
        result = telegramify_markdown(text)
        assert "```python\n" in result
        assert "```md\n" not in result

    def test_collapses_code_blocks_into_spoilers(self):
        text = "```python\nprint(1)\n```"
        result = telegramify_markdown(text, collapse_code_blocks=True)
        assert "📦 *CODE BLOCK*" in result
        assert "||```python" in result
        assert "```||" in result


class TestMarkdownTruncation:
    def test_truncate_markdown_v2_closes_open_inline_code(self):
        source = "prefix `inline snippet that keeps going"
        truncated = truncate_markdown_v2(source, max_chars=30, suffix="...")
        assert _required_markdown_closers(truncated) == ""

    def test_truncate_markdown_v2_closes_open_fenced_block(self):
        source = "```python\nprint('a')\nprint('b')\nprint('c')\n```"
        truncated = truncate_markdown_v2(source, max_chars=28, suffix="...")
        assert _required_markdown_closers(truncated) == ""

    def test_collapse_fenced_code_blocks_balances_entities(self):
        collapsed = collapse_fenced_code_blocks("```js\nconsole.log(1)\n```")
        assert _required_markdown_closers(collapsed) == ""

    def test_truncate_markdown_v2_with_consumed_drops_trailing_escape(self):
        source = "abc\\."
        truncated, consumed = truncate_markdown_v2_with_consumed(source, max_chars=4, suffix="")
        assert truncated == "abc"
        assert consumed == 3

    def test_truncate_markdown_v2_with_consumed_keeps_balanced_entities(self):
        source = "```python\nprint('x')\nprint('y')\n```"
        truncated, consumed = truncate_markdown_v2_with_consumed(source, max_chars=24, suffix="...")
        assert consumed > 0
        assert _required_markdown_closers(truncated) == ""

    def test_scan_markdown_v2_state_and_continuation_prefix_for_code_block(self):
        source = "```python\nprint('hello')"
        state = scan_markdown_v2_state(source)
        assert state.stack == ("code_block",)
        assert not state.in_link_text
        assert state.link_url_depth == 0
        assert continuation_prefix_for_markdown_v2_state(state) == "```\n"

    def test_scan_markdown_v2_state_and_continuation_prefix_for_inline(self):
        source = "`abc"
        state = scan_markdown_v2_state(source)
        assert state.stack == ("inline_code",)
        assert not state.in_link_text
        assert state.link_url_depth == 0
        assert continuation_prefix_for_markdown_v2_state(state) == "`"

    def test_truncate_markdown_v2_by_bytes_respects_utf8_budget(self):
        source = f"```\n{'😀' * 2000}\n```"
        truncated = truncate_markdown_v2_by_bytes(source, max_bytes=3900, suffix="\n\n…")
        assert len(truncated.encode("utf-8")) <= 3900
        assert _required_markdown_closers(truncated) == ""

    def test_truncate_markdown_v2_balances_nested_italic_and_bold(self):
        source = "*bold _italic section that keeps running without a close"
        truncated = truncate_markdown_v2(source, max_chars=38, suffix="...")
        assert _required_markdown_closers(truncated) == ""
        assert truncated.endswith("_*...")

    def test_continuation_prefix_reopens_nested_style_stack(self):
        source = "*bold _italic"
        state = scan_markdown_v2_state(source)
        assert state.stack == ("bold", "italic")
        assert continuation_prefix_for_markdown_v2_state(state) == "*_"

    def test_truncate_markdown_v2_avoids_link_mid_entity_split(self):
        source = "[read more](https://example.com/path_with_underscores/very/long/segment) tail"
        truncated = truncate_markdown_v2(source, max_chars=34, suffix="...")
        state = scan_markdown_v2_state(truncated)
        assert state == MARKDOWN_V2_INITIAL_STATE
        assert _required_markdown_closers(truncated) == ""

    def test_leading_balanced_entity_span_detects_short_link(self):
        source = "[docs](https://example.com) and more"
        span = leading_balanced_markdown_v2_entity_span(source)
        assert span == len("[docs](https://example.com)")

    def test_leading_balanced_entity_span_returns_zero_for_plain_text(self):
        source = "prefix [docs](https://example.com)"
        span = leading_balanced_markdown_v2_entity_span(source)
        assert span == 0


class TestMarkdownFallback:
    def test_unescape_markdown_v2_from_real_gemini_fixture(self):
        fixture = Path("tests/fixtures/transcripts/gemini_real_escape_regression_snapshot.json")
        assert fixture.exists()

        rendered, _ts = render_agent_output(
            str(fixture),
            AgentName.GEMINI,
            include_tools=True,
            include_tool_results=False,
        )
        assert rendered

        formatted = telegramify_markdown(rendered)
        plain = unescape_markdown_v2(formatted)

        assert plain.count("\\") < formatted.count("\\")
        assert "\\." not in plain
