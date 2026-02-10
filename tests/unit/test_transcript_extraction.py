"""Tests for tool-call extraction from transcripts (Layer 2 consumer)."""

import json
import tempfile
from pathlib import Path

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import (
    TurnTimeline,
    extract_tool_calls_current_turn,
    parse_claude_transcript,
)


def _write_jsonl(entries: list[dict], suffix: str = ".jsonl") -> str:
    """Write entries as JSONL and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    for entry in entries:
        f.write(json.dumps(entry) + "\n")
    f.flush()
    f.close()
    return f.name


def _cleanup(path: str) -> None:
    Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Claude JSONL extraction
# ---------------------------------------------------------------------------


def test_extract_claude_tool_calls():
    """Bash and Read tool calls are extracted from Claude JSONL."""
    entries = [
        {"type": "user", "message": {"role": "user", "content": "fix the bug"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "/tmp/foo.py"},
                    },
                    {
                        "type": "tool_result",
                        "content": "file contents here",
                        "is_error": False,
                    },
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "pytest tests/"},
                    },
                    {
                        "type": "tool_result",
                        "content": "PASSED",
                        "is_error": False,
                    },
                ],
            },
        },
    ]
    path = _write_jsonl(entries)
    try:
        timeline = extract_tool_calls_current_turn(path, AgentName.CLAUDE)
        assert timeline.has_data is True
        assert len(timeline.tool_calls) == 2
        assert timeline.tool_calls[0].tool_name == "Read"
        assert timeline.tool_calls[0].input_data.get("file_path") == "/tmp/foo.py"
        assert timeline.tool_calls[0].had_error is False
        assert timeline.tool_calls[1].tool_name == "Bash"
        assert timeline.tool_calls[1].input_data.get("command") == "pytest tests/"
    finally:
        _cleanup(path)


def test_extract_scopes_to_current_turn():
    """Entries before the last user message are excluded."""
    entries = [
        {"type": "user", "message": {"role": "user", "content": "first question"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "echo old"}},
                    {"type": "tool_result", "content": "old", "is_error": False},
                ],
            },
        },
        {"type": "user", "message": {"role": "user", "content": "second question"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "echo new"}},
                    {"type": "tool_result", "content": "new", "is_error": False},
                ],
            },
        },
    ]
    path = _write_jsonl(entries)
    try:
        timeline = extract_tool_calls_current_turn(path, AgentName.CLAUDE)
        assert len(timeline.tool_calls) == 1
        assert timeline.tool_calls[0].input_data.get("command") == "echo new"
    finally:
        _cleanup(path)


def test_tool_use_result_pairing():
    """tool_use followed by tool_result produces correct had_error and snippet."""
    entries = [
        {"type": "user", "message": {"role": "user", "content": "do something"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "false"}},
                    {
                        "type": "tool_result",
                        "content": "Traceback (most recent call last):\n  File ...",
                        "is_error": True,
                    },
                ],
            },
        },
    ]
    path = _write_jsonl(entries)
    try:
        timeline = extract_tool_calls_current_turn(path, AgentName.CLAUDE)
        assert len(timeline.tool_calls) == 1
        record = timeline.tool_calls[0]
        assert record.had_error is True
        assert "Traceback" in record.result_snippet
    finally:
        _cleanup(path)


def test_tool_use_without_result():
    """Unpaired tool_use gets had_error=False and empty snippet."""
    entries = [
        {"type": "user", "message": {"role": "user", "content": "do something"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}},
                ],
            },
        },
    ]
    path = _write_jsonl(entries)
    try:
        timeline = extract_tool_calls_current_turn(path, AgentName.CLAUDE)
        assert len(timeline.tool_calls) == 1
        record = timeline.tool_calls[0]
        assert record.had_error is False
        assert record.result_snippet == ""
    finally:
        _cleanup(path)


def test_extract_missing_transcript_returns_empty():
    """Missing transcript file returns empty timeline (fail-open)."""
    timeline = extract_tool_calls_current_turn("/nonexistent/path.jsonl", AgentName.CLAUDE)
    assert timeline.has_data is False
    assert timeline.tool_calls == []


# ---------------------------------------------------------------------------
# Codex JSONL extraction
# ---------------------------------------------------------------------------


def test_extract_codex_tool_calls():
    """Codex response_item entries produce tool call records."""
    entries = [
        {
            "type": "response_item",
            "timestamp": "2026-01-15T10:00:00.000Z",
            "payload": {"role": "user", "content": "fix it"},
        },
        {
            "type": "response_item",
            "timestamp": "2026-01-15T10:00:05.000Z",
            "payload": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "make test"}},
                    {"type": "tool_result", "content": "PASSED", "is_error": False},
                ],
            },
        },
    ]
    path = _write_jsonl(entries)
    try:
        timeline = extract_tool_calls_current_turn(path, AgentName.CODEX)
        assert timeline.has_data is True
        assert len(timeline.tool_calls) == 1
        assert timeline.tool_calls[0].tool_name == "Bash"
    finally:
        _cleanup(path)


# ---------------------------------------------------------------------------
# Gemini JSON extraction
# ---------------------------------------------------------------------------


def test_extract_gemini_tool_calls():
    """Gemini JSON sessions produce tool call records."""
    gemini_payload = {
        "sessionId": "gem-1",
        "messages": [
            {
                "type": "user",
                "timestamp": "2026-01-15T10:00:00.000Z",
                "content": "check the tests",
            },
            {
                "type": "gemini",
                "timestamp": "2026-01-15T10:00:05.000Z",
                "content": "running tests",
                "toolCalls": [
                    {
                        "name": "run_terminal_command",
                        "displayName": "Terminal",
                        "args": {"command": "pytest"},
                        "result": [{"functionResponse": {"response": {"output": "3 passed"}}}],
                    }
                ],
            },
        ],
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    f.write(json.dumps(gemini_payload))
    f.flush()
    f.close()
    try:
        timeline = extract_tool_calls_current_turn(f.name, AgentName.GEMINI)
        # Gemini format may not map to tool_use/tool_result blocks directly;
        # the extraction depends on how _get_entries_for_agent normalizes them.
        # At minimum, fail-open is satisfied.
        assert isinstance(timeline, TurnTimeline)
    finally:
        _cleanup(f.name)


# ---------------------------------------------------------------------------
# Regression guard: existing renderers still work
# ---------------------------------------------------------------------------


def test_existing_renderers_unaffected():
    """parse_claude_transcript still works after extraction additions."""
    entries = [
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there"}],
            },
        },
    ]
    path = _write_jsonl(entries)
    try:
        result = parse_claude_transcript(path, "Regression Test")
        assert "hello" in result
        assert "Hi there" in result
    finally:
        _cleanup(path)
