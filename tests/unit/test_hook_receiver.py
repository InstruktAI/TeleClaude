"""Unit tests for hook receiver error handling."""

import argparse

import pytest


def test_receiver_emits_error_event_on_normalize_failure(monkeypatch):
    from teleclaude.hooks import receiver

    sent = []

    def fake_send(name, payload):
        sent.append((name, payload))

    def fake_normalize(_event_type, _data):
        raise ValueError("boom")

    monkeypatch.setattr(receiver, "mcp_send", fake_send)
    monkeypatch.setattr(receiver, "_get_adapter", lambda _agent: fake_normalize)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.setenv("TELECLAUDE_SESSION_ID", "sess-1")

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 1
    assert sent
    event_name, payload = sent[0]
    assert event_name == "teleclaude__handle_agent_event"
    assert payload["session_id"] == "sess-1"
    assert payload["event_type"] == "error"
    data = payload["data"]
    assert data["message"] == "boom"
    assert data["source"] == "hook_receiver"
    assert data["details"] == {"agent": "claude", "event_type": "stop"}
