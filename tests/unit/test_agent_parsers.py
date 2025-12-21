"""Unit tests for agent log parsers."""

from teleclaude.core.agent_parsers import CodexParser


def test_codex_parser_stop():
    parser = CodexParser()
    # Schema: {"type": "event_msg", "payload": {"type": "agent_message", "message": "..."}}
    line = '{"type": "event_msg", "payload": {"type": "agent_message", "message": "Done."}}'

    events = list(parser.parse_line(line))
    assert len(events) == 1
    assert events[0].event_type == "stop"


def test_codex_parser_notification():
    parser = CodexParser()
    line = (
        '{"type": "response_item", '
        '"payload": {"type": "message", "role": "model", '
        '"content": [{"type": "tool_use", "name": "AskQuestion", "input": {}}]}}'
    )

    events = list(parser.parse_line(line))
    assert len(events) == 1
    assert events[0].event_type == "notification"
