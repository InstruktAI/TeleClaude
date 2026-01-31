"""Test transcript extraction functions used by the summarizer pipeline."""

import json

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import collect_transcript_messages, extract_last_agent_message


def test_extract_last_agent_message_claude(tmp_path):
    """Test extracting last assistant message from Claude transcript."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"User 1"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 1"}]}}
{"type":"user","message":{"role":"user","content":"User 2"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 2"}]}}
"""
    f = tmp_path / "claude.jsonl"
    f.write_text(jsonl_content)

    result = extract_last_agent_message(str(f), AgentName.CLAUDE)
    assert result is not None
    assert "Response 2" in result
    assert "Response 1" not in result


def test_extract_last_agent_message_multiple(tmp_path):
    """Test extracting multiple last assistant messages."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"User 1"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 1"}]}}
{"type":"user","message":{"role":"user","content":"User 2"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 2"}]}}
"""
    f = tmp_path / "claude.jsonl"
    f.write_text(jsonl_content)

    result = extract_last_agent_message(str(f), AgentName.CLAUDE, count=2)
    assert result is not None
    assert "Response 1" in result
    assert "Response 2" in result


def test_extract_last_agent_message_filters_tool_use(tmp_path):
    """Test that tool_use and thinking blocks are filtered out."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"Help me"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"I should use a tool"},{"type":"tool_use","name":"grep","input":{}},{"type":"text","text":"I found the file"}]}}
"""
    f = tmp_path / "claude_tools.jsonl"
    f.write_text(jsonl_content)

    result = extract_last_agent_message(str(f), AgentName.CLAUDE)
    assert result is not None
    assert "I found the file" in result
    assert "tool_use" not in result
    assert "I should use a tool" not in result


def test_extract_last_agent_message_no_assistant(tmp_path):
    """Test transcript with no assistant messages returns None."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"Hello"}}
"""
    f = tmp_path / "claude_empty.jsonl"
    f.write_text(jsonl_content)

    result = extract_last_agent_message(str(f), AgentName.CLAUDE)
    assert result is None


def test_collect_transcript_messages_claude(tmp_path):
    """Test collecting message pairs from Claude transcript."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"User 1"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 1"}]}}
{"type":"user","message":{"role":"user","content":"User 2"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 2"}]}}
"""
    f = tmp_path / "claude.jsonl"
    f.write_text(jsonl_content)

    messages = collect_transcript_messages(str(f), AgentName.CLAUDE)
    assert len(messages) == 4
    assert messages[0] == ("user", "User 1")
    assert messages[1] == ("assistant", "Response 1")
    assert messages[2] == ("user", "User 2")
    assert messages[3] == ("assistant", "Response 2")


def test_collect_transcript_messages_gemini(tmp_path):
    """Test collecting message pairs from Gemini transcript."""
    gemini_payload = {
        "sessionId": "gemini-1",
        "messages": [
            {
                "type": "user",
                "timestamp": "2025-12-15T12:00:00.000Z",
                "content": "Gemini User 1",
            },
            {
                "type": "gemini",
                "timestamp": "2025-12-15T12:00:02.000Z",
                "content": "Gemini Response 1",
                "thoughts": [{"description": "Thinking"}],
            },
        ],
    }
    f = tmp_path / "gemini.json"
    f.write_text(json.dumps(gemini_payload))

    messages = collect_transcript_messages(str(f), AgentName.GEMINI)
    assert any(role == "user" and "Gemini User 1" in text for role, text in messages)


def test_collect_transcript_messages_codex(tmp_path):
    """Test collecting message pairs from Codex transcript."""
    entries = [
        json.dumps(
            {
                "type": "response_item",
                "payload": {"role": "user", "content": "Codex User 1"},
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Codex Response 1"}],
                },
            }
        ),
    ]
    f = tmp_path / "codex.jsonl"
    f.write_text("\n".join(entries))

    messages = collect_transcript_messages(str(f), AgentName.CODEX)
    assert any(role == "user" and "Codex User 1" in text for role, text in messages)
    assert any(role == "assistant" and "Codex Response 1" in text for role, text in messages)
