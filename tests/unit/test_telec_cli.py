"""Unit tests for telec CLI parsing."""

from teleclaude.cli.telec import parse_telec_command


def test_parse_claude_start() -> None:
    parsed = parse_telec_command(["/claude", "fast", "hello"])
    assert parsed.action == "start"
    assert parsed.agent == "claude"
    assert parsed.args == ["fast", "hello"]


def test_parse_agent_start() -> None:
    parsed = parse_telec_command(["/agent", "gemini", "slow", "test"])
    assert parsed.action == "start"
    assert parsed.agent == "gemini"
    assert parsed.args == ["slow", "test"]


def test_parse_agent_resume() -> None:
    parsed = parse_telec_command(["/agent_resume", "abc123"])
    assert parsed.action == "resume"
    assert parsed.session_id == "abc123"
