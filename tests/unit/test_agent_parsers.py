"""Unit tests for agent log parsers."""

from teleclaude.core.agent_parsers import CodexParser


def test_codex_parser_stop():
    parser = CodexParser()
    # Schema: {"type": "response_item", "payload": {"role": "model", "content": [...]}}
    line = '{"type": "response_item", "payload": {"role": "model", "content": [{"type": "text", "text": "Done."}]}}'

    events = list(parser.parse_line(line))
    assert len(events) == 1
    assert events[0].event_type == "stop"


def test_codex_parser_notification():
    parser = CodexParser()
    line = '{"type": "response_item", "payload": {"role": "model", "content": [{"type": "tool_use", "name": "AskQuestion", "input": {}}]}}'

    events = list(parser.parse_line(line))
    # Should yield stop (as it's a model message) AND notification
    assert len(events) >= 1

    notification = next((e for e in events if e.event_type == "notification"), None)
    assert notification is not None
