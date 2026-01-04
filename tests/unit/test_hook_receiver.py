"""Unit tests for hook receiver error handling."""

import argparse

import pytest


def test_receiver_emits_error_event_on_normalize_failure(monkeypatch):
    from teleclaude.hooks import receiver

    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_normalize(_event_type, _data):
        raise ValueError("boom")

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_get_adapter", lambda _agent: fake_normalize)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.setenv("TELECLAUDE_SESSION_ID", "sess-1")

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 1
    assert sent
    session_id, event_type, data = sent[0]
    assert session_id == "sess-1"
    assert event_type == "error"
    assert data["message"] == "boom"
    assert data["source"] == "hook_receiver"
    assert data["details"] == {"agent": "claude", "event_type": "stop"}


def test_receiver_requires_session_id(monkeypatch):
    from teleclaude.hooks import receiver

    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.setattr(receiver, "_get_parent_process_info", lambda: (None, None))
    monkeypatch.delenv("TELECLAUDE_SESSION_ID", raising=False)

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 1
    assert not sent


def test_receiver_recovers_session_from_tty(monkeypatch):
    from teleclaude.hooks import receiver

    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.setattr(receiver, "_get_parent_process_info", lambda: (123, "/dev/ttys001"))
    monkeypatch.setattr(receiver, "ensure_terminal_session", lambda **_kwargs: "sess-tty")
    monkeypatch.delenv("TELECLAUDE_SESSION_ID", raising=False)

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "sess-tty"
    assert event_type == "stop"
