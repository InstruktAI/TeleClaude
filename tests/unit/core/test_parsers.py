"""Characterization tests for teleclaude.core.parsers."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from teleclaude.core.parsers import LogEvent, LogParser


class _MinimalParser(LogParser):
    """Minimal concrete implementation for ABC testing."""

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix == ".log"

    def extract_session_id(self, file_path: Path) -> str | None:
        return None

    def parse_line(self, line: str) -> Generator[LogEvent, None, None]:
        if "stop" in line:
            yield LogEvent(event_type="agent_stop", data={}, timestamp=1.0)

    def extract_last_turn(self, file_path: Path) -> str:
        return ""


class TestLogEvent:
    @pytest.mark.unit
    def test_event_holds_required_fields(self):
        event = LogEvent(event_type="agent_stop", data={"key": "val"}, timestamp=1234.5)
        assert event.event_type == "agent_stop"
        assert event.data == {"key": "val"}
        assert event.timestamp == 1234.5


class TestLogParserAbstract:
    @pytest.mark.unit
    def test_concrete_subclass_instantiates(self):
        parser = _MinimalParser()
        assert parser is not None

    @pytest.mark.unit
    def test_can_parse_delegates_to_suffix(self):
        parser = _MinimalParser()
        assert parser.can_parse(Path("session.log")) is True
        assert parser.can_parse(Path("session.jsonl")) is False

    @pytest.mark.unit
    def test_parse_line_yields_events(self):
        parser = _MinimalParser()
        events = list(parser.parse_line("agent_stop signal"))
        assert len(events) == 1
        assert events[0].event_type == "agent_stop"

    @pytest.mark.unit
    def test_parse_line_yields_nothing_for_empty(self):
        parser = _MinimalParser()
        events = list(parser.parse_line("no relevant content"))
        assert events == []

    @pytest.mark.unit
    def test_extract_session_id_returns_none_for_minimal(self):
        parser = _MinimalParser()
        assert parser.extract_session_id(Path("file.log")) is None
