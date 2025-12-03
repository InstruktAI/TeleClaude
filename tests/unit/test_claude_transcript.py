"""Test claude_transcript parser."""

import tempfile
from pathlib import Path

from teleclaude.utils.claude_transcript import parse_claude_transcript


def test_parse_claude_transcript_with_title():
    """Test parsing JSONL with session title."""
    # Create test JSONL
    jsonl_content = """{"type":"summary","summary":"Test summary"}
{"type":"user","message":{"role":"user","content":"hello"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"User said hello"},{"type":"text","text":"Hi there"}]}}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(jsonl_content)
        f.flush()

        result = parse_claude_transcript(f.name, "Test Session")

        # Verify title
        assert "# Test Session" in result

        # Verify user message
        assert "## 👤 User" in result
        assert "hello" in result

        # Verify assistant thinking (italic)
        assert "*User said hello*" in result

        # Verify assistant text (no bold)
        assert "Hi there" in result

        # Cleanup
        Path(f.name).unlink()


def test_parse_claude_transcript_code_blocks():
    """Test that code blocks in thinking are not italicized."""
    jsonl_content = """{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"Check this code:\\n```python\\nprint('test')\\n```\\nLooks good"}]}}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(jsonl_content)
        f.flush()

        result = parse_claude_transcript(f.name, "Code Test")

        # Code block should not be italicized
        assert "```python" in result
        assert "print('test')" in result
        assert "```" in result

        # Text outside code block should be italicized
        assert "*Check this code:*" in result
        assert "*Looks good*" in result

        Path(f.name).unlink()


def test_parse_claude_transcript_file_not_found():
    """Test handling of missing file."""
    result = parse_claude_transcript("/nonexistent/file.jsonl", "Test")
    assert "Transcript file not found" in result


def test_parse_claude_transcript_grouping():
    """Test that consecutive messages from same role are grouped."""
    jsonl_content = """{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"Thinking 1"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 1"}]}}
{"type":"user","message":{"role":"user","content":"User 1"}}
{"type":"user","message":{"role":"user","content":"User 2"}}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(jsonl_content)
        f.flush()

        result = parse_claude_transcript(f.name, "Grouping Test")

        # Should only have ONE assistant header (messages grouped)
        assert result.count("## 🤖 Assistant") == 1

        # Should only have ONE user header (messages grouped)
        assert result.count("## 👤 User") == 1

        # Both user messages should be present
        assert "User 1" in result
        assert "User 2" in result

        Path(f.name).unlink()


def test_parse_claude_transcript_spacing():
    """Test proper spacing between sections."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"hi"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"Processing"},{"type":"text","text":"Hello"}]}}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(jsonl_content)
        f.flush()

        result = parse_claude_transcript(f.name, "Spacing Test")

        # Should have blank line after thinking section before text
        lines = result.split("\n")

        # Find thinking line and next non-empty line
        thinking_idx = next(i for i, line in enumerate(lines) if "*Processing*" in line)

        # Next non-empty line should be the bold text
        next_content_idx = next(
            i for i in range(thinking_idx + 1, len(lines)) if lines[i].strip() and not lines[i].strip() == ""
        )

        # Should be exactly one blank line between
        assert next_content_idx == thinking_idx + 2
        assert lines[thinking_idx + 1] == ""

        Path(f.name).unlink()


def test_parse_claude_transcript_with_timestamps():
    """Test that timestamps are included in section headers."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"hello"},"timestamp":"2025-11-28T10:30:00.000Z"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hi!"}]},"timestamp":"2025-11-28T10:30:05.000Z"}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(jsonl_content)
        f.flush()

        result = parse_claude_transcript(f.name, "Timestamp Test", tail_chars=0)

        # Verify timestamps appear in headers (format depends on current date)
        # Should contain time component
        assert "10:30:00" in result or "2025-11-28 10:30:00" in result
        assert "10:30:05" in result or "2025-11-28 10:30:05" in result

        # Each entry gets its own header when timestamps are present
        assert result.count("👤 User") == 1
        assert result.count("🤖 Assistant") == 1

        Path(f.name).unlink()


def test_parse_claude_transcript_timestamp_filtering():
    """Test filtering by since_timestamp."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"msg1"},"timestamp":"2025-11-28T10:00:00.000Z"}
{"type":"user","message":{"role":"user","content":"msg2"},"timestamp":"2025-11-28T10:30:00.000Z"}
{"type":"user","message":{"role":"user","content":"msg3"},"timestamp":"2025-11-28T11:00:00.000Z"}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(jsonl_content)
        f.flush()

        # Filter to only messages after 10:15
        result = parse_claude_transcript(
            f.name, "Filter Test", since_timestamp="2025-11-28T10:15:00.000Z", tail_chars=0
        )

        # msg1 should be filtered out (before 10:15)
        assert "msg1" not in result
        # msg2 and msg3 should be present
        assert "msg2" in result
        assert "msg3" in result

        Path(f.name).unlink()


def test_parse_claude_transcript_until_timestamp():
    """Test filtering by until_timestamp."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"msg1"},"timestamp":"2025-11-28T10:00:00.000Z"}
{"type":"user","message":{"role":"user","content":"msg2"},"timestamp":"2025-11-28T10:30:00.000Z"}
{"type":"user","message":{"role":"user","content":"msg3"},"timestamp":"2025-11-28T11:00:00.000Z"}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(jsonl_content)
        f.flush()

        # Filter to only messages before 10:45
        result = parse_claude_transcript(
            f.name, "Filter Test", until_timestamp="2025-11-28T10:45:00.000Z", tail_chars=0
        )

        # msg1 and msg2 should be present
        assert "msg1" in result
        assert "msg2" in result
        # msg3 should be filtered out (after 10:45)
        assert "msg3" not in result

        Path(f.name).unlink()


def test_parse_claude_transcript_tail_chars():
    """Test truncation with tail_chars limit."""
    # Create a large content
    jsonl_content = """{"type":"user","message":{"role":"user","content":"START_MARKER this is some content that should be truncated away"}}
{"type":"user","message":{"role":"user","content":"MIDDLE content here"}}
{"type":"user","message":{"role":"user","content":"END_MARKER this is the final message"}}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(jsonl_content)
        f.flush()

        # Get full content first
        full_result = parse_claude_transcript(f.name, "Tail Test", tail_chars=0)
        full_len = len(full_result)

        # Now get truncated (last 100 chars)
        truncated = parse_claude_transcript(f.name, "Tail Test", tail_chars=100)

        # Should be truncated
        assert len(truncated) <= full_len
        # Should have truncation indicator
        assert "truncated" in truncated.lower()
        # End content should be present
        assert "END_MARKER" in truncated

        Path(f.name).unlink()
