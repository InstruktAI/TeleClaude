"""Test claude_transcript parser."""

import json
import tempfile
from pathlib import Path

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import (
    get_transcript_parser_info,
    parse_claude_transcript,
    parse_codex_transcript,
    parse_gemini_transcript,
    parse_session_transcript,
)


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

        # Verify assistant thinking text
        assert "User said hello" in result

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

        # Text outside code block
        assert "Check this code:" in result
        assert "Looks good" in result

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
        thinking_idx = next(i for i, line in enumerate(lines) if "Processing" in line)

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
        # Time is converted to local timezone, so check for presence of timestamp pattern
        # The exact time may vary by timezone (e.g., 10:30 UTC -> 11:30 CET)
        assert "2025-11-28" in result
        assert ":30:00" in result  # Both messages are at :30:00 and :30:05
        assert ":30:05" in result

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


def test_get_transcript_parser_info_gemini():
    """Gemini parser metadata should be returned when requested."""
    info = get_transcript_parser_info(AgentName.GEMINI)
    assert info.display_name == "Gemini"
    assert info.file_prefix == "gemini"


def test_parse_session_transcript_agent_override(tmp_path):
    """Agent-specific parser helpers still honor the shared renderer."""
    session_file = tmp_path / "agent-session.jsonl"
    gemini_payload = {
        "sessionId": "agent-session",
        "messages": [
            {
                "type": "user",
                "timestamp": "2025-12-15T12:00:00.000Z",
                "content": "hi",
            },
            {
                "type": "gemini",
                "timestamp": "2025-12-15T12:00:02.000Z",
                "content": "there",
                "thoughts": [{"description": "Thinking"}],
            },
        ],
    }
    session_file.write_text(json.dumps(gemini_payload), encoding="utf-8")

    result = parse_session_transcript(
        str(session_file),
        "Agent Test",
        agent_name=AgentName.GEMINI,
        tail_chars=0,
    )
    assert "# Agent Test" in result
    assert "hi" in result
    assert "there" in result


def test_parse_session_transcript_escape_triple_backticks(tmp_path):
    """Optional backtick escaping should replace ``` with a safe sequence."""
    session_file = tmp_path / "claude-backticks.jsonl"
    entries = [
        json.dumps(
            {
                "timestamp": "2025-12-15T12:00:00.000Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "```py\nprint('hi')\n```"}],
                },
            }
        )
    ]
    session_file.write_text("\n".join(entries), encoding="utf-8")

    raw = parse_session_transcript(
        str(session_file),
        "Backticks Test",
        agent_name=AgentName.CLAUDE,
        tail_chars=0,
    )
    assert "```" in raw

    escaped = parse_session_transcript(
        str(session_file),
        "Backticks Test",
        agent_name=AgentName.CLAUDE,
        tail_chars=0,
        escape_triple_backticks=True,
    )
    assert "`\u200b``" in escaped
    assert "```" not in escaped


def test_parse_codex_transcript(tmp_path):
    """Codex transcripts normalize into markdown headings."""
    session_file = tmp_path / "codex.jsonl"
    entries = [
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2025-12-15T21:00:00.000Z",
                "payload": {"role": "user", "content": "codex user request"},
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2025-12-15T21:00:05.000Z",
                "payload": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "codex assistant reply"}],
                },
            }
        ),
    ]
    session_file.write_text("\n".join(entries), encoding="utf-8")

    result = parse_codex_transcript(str(session_file), "Codex Test", tail_chars=0)
    assert "Codex Test" in result
    assert "codex user request" in result
    assert "codex assistant reply" in result


def test_parse_codex_transcript_reasoning_blocks(tmp_path):
    """Codex response_item reasoning payloads render as assistant thinking blocks."""
    session_file = tmp_path / "codex-reasoning.jsonl"
    entries = [
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2025-12-15T21:00:00.000Z",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "prompt"}]},
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2025-12-15T21:00:01.000Z",
                "payload": {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "Reasoning line"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2025-12-15T21:00:02.000Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "final answer"}],
                },
            }
        ),
    ]
    session_file.write_text("\n".join(entries), encoding="utf-8")

    result = parse_codex_transcript(str(session_file), "Codex Reasoning", tail_chars=0)
    assert "Reasoning line" in result
    assert "*Reasoning line*" in result
    assert "final answer" in result


def test_parse_codex_transcript_tail_chars_prefers_recent_sections(tmp_path):
    """Codex tail truncation should keep the newest content visible."""
    session_file = tmp_path / "codex-tail.jsonl"
    entries = [
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2025-12-15T21:00:00.000Z",
                "payload": {"role": "user", "content": "EARLY_MARKER this should be truncated away"},
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2025-12-15T21:00:02.000Z",
                "payload": {"role": "assistant", "content": [{"type": "text", "text": "middle content"}]},
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2025-12-15T21:00:04.000Z",
                "payload": {"role": "user", "content": "LATEST_MARKER keep this visible"},
            }
        ),
    ]
    session_file.write_text("\n".join(entries), encoding="utf-8")

    full = parse_codex_transcript(str(session_file), "Codex Tail Test", tail_chars=0)
    assert "EARLY_MARKER" in full
    assert "LATEST_MARKER" in full

    truncated = parse_codex_transcript(str(session_file), "Codex Tail Test", tail_chars=200)
    assert "truncated" in truncated.lower()
    assert "LATEST_MARKER" in truncated
    assert "EARLY_MARKER" not in truncated


def test_parse_gemini_transcript(tmp_path):
    """Gemini sessions include thinking + tool blocks plus NORMAL text."""
    session_file = tmp_path / "gemini.json"
    gemini_payload = {
        "sessionId": "abc",
        "messages": [
            {
                "type": "user",
                "timestamp": "2025-12-15T22:00:00.000Z",
                "content": "gemini user input",
            },
            {
                "type": "gemini",
                "timestamp": "2025-12-15T22:00:02.000Z",
                "content": "gemini assistant answer",
                "thoughts": [{"description": "Considering options"}, {"description": ""}],
                "toolCalls": [
                    {
                        "name": "search_file_content",
                        "displayName": "Search",
                        "args": {"pattern": "get_session_data"},
                        "result": [{"functionResponse": {"response": {"output": "no matches found"}}}],
                    }
                ],
            },
        ],
    }
    session_file.write_text(json.dumps(gemini_payload), encoding="utf-8")

    result = parse_gemini_transcript(str(session_file), "Gemini Test", tail_chars=0)
    assert "Gemini Test" in result
    assert "gemini user input" in result
    assert "gemini assistant answer" in result
    assert "Considering options" in result
    assert "**`Search`**" in result  # Tool use indicator
    assert "TOOL RESPONSE" in result
    assert "> no matches found" in result


def test_parse_transcript_collapses_tool_results(tmp_path):
    """Tool results can be emitted as spoilers when collapse_tool_results is set."""
    session_file = tmp_path / "claude.jsonl"
    session_file.write_text(
        json.dumps(
            {
                "type": "message",
                "timestamp": "2025-12-15T21:00:03.000Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_result",
                            "content": "secret output",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = parse_claude_transcript(
        str(session_file),
        "Tool Result Collapse",
        tail_chars=0,
        collapse_tool_results=True,
    )

    assert "TOOL RESPONSE (tap to reveal)" in result
    assert "||secret output||" in result
