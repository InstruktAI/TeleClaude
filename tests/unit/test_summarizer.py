"""Test summarizer helper functions."""

import json

from teleclaude.core.agents import AgentName
from teleclaude.core.summarizer import extract_recent_exchanges


def test_extract_recent_exchanges_claude(tmp_path):
    """Test extracting text exchanges from Claude transcript."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"User 1"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 1"}]}}
{"type":"user","message":{"role":"user","content":"User 2"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response 2"}]}}
"""
    f = tmp_path / "claude.jsonl"
    f.write_text(jsonl_content)

    result = extract_recent_exchanges(str(f), AgentName.CLAUDE, n_exchanges=2)

    assert "User: User 1" in result
    assert "Assistant: Response 1" in result
    assert "User: User 2" in result
    assert "Assistant: Response 2" in result


def test_extract_recent_exchanges_tool_filtering(tmp_path):
    """Test filtering of tool use and thinking blocks."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"Help me"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"I should use a tool"},{"type":"tool_use","name":"grep","input":{}},{"type":"text","text":"I found the file"}]}}
{"type":"tool_result","tool_result":"some data"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"And here is the content"}]}}
"""
    f = tmp_path / "claude_tools.jsonl"
    f.write_text(jsonl_content)

    result = extract_recent_exchanges(str(f), AgentName.CLAUDE)

    assert "User: Help me" in result
    assert "I should use a tool" not in result
    assert "tool_use" not in result
    # Note: Logic appends assistant messages to same exchange if no new user message
    # So "I found the file" and "And here is the content" might be concatenated
    assert "Assistant: I found the file\nAnd here is the content" in result


def test_extract_recent_exchanges_no_user(tmp_path):
    """Test transcript with no user messages (empty result)."""
    jsonl_content = """{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]}}
"""
    f = tmp_path / "claude_empty.jsonl"
    f.write_text(jsonl_content)

    result = extract_recent_exchanges(str(f), AgentName.CLAUDE)
    assert result == ""


def test_extract_recent_exchanges_user_only(tmp_path):
    """Test user message without assistant response."""
    jsonl_content = """{"type":"user","message":{"role":"user","content":"Just saying hi"}}
"""
    f = tmp_path / "claude_user_only.jsonl"
    f.write_text(jsonl_content)

    result = extract_recent_exchanges(str(f), AgentName.CLAUDE)
    assert "User: Just saying hi" in result
    # Assistant part might be empty or not present
    # My implementation appends "Assistant: " if ex['assistant'] is present
    # Check implementation: if ex['assistant']: output_lines.append(...)
    assert "Assistant:" not in result


def test_extract_recent_exchanges_gemini(tmp_path):
    """Test extracting exchanges from Gemini transcript."""
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

    result = extract_recent_exchanges(str(f), AgentName.GEMINI)

    assert "User: Gemini User 1" in result
    assert "Assistant: Gemini Response 1" in result
    assert "Thinking" not in result


def test_extract_recent_exchanges_codex(tmp_path):
    """Test extracting exchanges from Codex transcript."""
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

    result = extract_recent_exchanges(str(f), AgentName.CODEX)

    assert "User: Codex User 1" in result
    assert "Assistant: Codex Response 1" in result


def test_extract_recent_exchanges_limit(tmp_path):
    """Test n_exchanges limit."""
    jsonl_content = ""
    for i in range(5):
        jsonl_content += json.dumps({"type": "user", "message": {"role": "user", "content": f"User {i}"}}) + "\n"
        jsonl_content += (
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": f"Resp {i}"}]},
                }
            )
            + "\n"
        )

    f = tmp_path / "claude_limit.jsonl"
    f.write_text(jsonl_content)

    result = extract_recent_exchanges(str(f), AgentName.CLAUDE, n_exchanges=2)

    assert "User: User 3" in result
    assert "User: User 4" in result
    assert "User: User 0" not in result
