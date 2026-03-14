"""Characterization tests for teleclaude.core.agent_parsers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teleclaude.core.agent_parsers import CodexParser


class TestCodexParserCanParse:
    @pytest.mark.unit
    def test_jsonl_file_returns_true(self):
        parser = CodexParser()
        assert parser.can_parse(Path("session.jsonl")) is True

    @pytest.mark.unit
    def test_non_jsonl_file_returns_false(self):
        parser = CodexParser()
        assert parser.can_parse(Path("session.log")) is False

    @pytest.mark.unit
    def test_txt_file_returns_false(self):
        parser = CodexParser()
        assert parser.can_parse(Path("output.txt")) is False


class TestCodexParserExtractSessionId:
    @pytest.mark.unit
    def test_extracts_session_id_from_session_meta_line(self, tmp_path):
        session_file = tmp_path / "rollout-2024-01-01-abc-123.jsonl"
        line = json.dumps({"type": "session_meta", "payload": {"id": "native-session-id"}})
        session_file.write_text(line + "\n")
        parser = CodexParser()
        result = parser.extract_session_id(session_file)
        assert result == "native-session-id"

    @pytest.mark.unit
    def test_returns_none_for_empty_file(self, tmp_path):
        session_file = tmp_path / "rollout.jsonl"
        session_file.write_text("")
        parser = CodexParser()
        result = parser.extract_session_id(session_file)
        assert result is None


class TestCodexParserParseLine:
    @pytest.mark.unit
    def test_agent_message_event_yields_agent_stop(self):
        parser = CodexParser()
        line = json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "agent_message"},
            }
        )
        events = list(parser.parse_line(line))
        assert len(events) == 1
        assert events[0].event_type == "agent_stop"

    @pytest.mark.unit
    def test_non_event_msg_type_yields_nothing(self):
        parser = CodexParser()
        line = json.dumps({"type": "session_meta", "payload": {"id": "123"}})
        events = list(parser.parse_line(line))
        assert events == []


class TestCodexParserExtractLastTurn:
    @pytest.mark.unit
    def test_returns_empty_for_no_assistant_content(self, tmp_path):
        session_file = tmp_path / "rollout.jsonl"
        lines = [
            json.dumps({"type": "session_meta", "payload": {"id": "abc"}}),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        parser = CodexParser()
        result = parser.extract_last_turn(session_file)
        assert result == ""

    @pytest.mark.unit
    def test_returns_last_assistant_text(self, tmp_path):
        session_file = tmp_path / "rollout.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Hello from assistant"}],
                    },
                }
            ),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        parser = CodexParser()
        result = parser.extract_last_turn(session_file)
        assert "Hello from assistant" in result
