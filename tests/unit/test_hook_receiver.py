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
    monkeypatch.setattr(receiver, "_session_exists", lambda _sid: True)
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


def test_receiver_exits_cleanly_without_session(monkeypatch):
    """Standalone sessions (not started via TeleClaude) should exit cleanly."""
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

    assert exc.value.code == 0  # Clean exit for standalone sessions
    assert not sent


def test_receiver_exits_cleanly_when_tmux_recovery_fails(monkeypatch):
    """When tmux recovery fails, exit cleanly (standalone session)."""
    from teleclaude.hooks import receiver

    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.setattr(receiver, "_get_parent_process_info", lambda: (123, "/dev/ttys001"))
    monkeypatch.setattr(receiver, "_find_session_by_tmux_name", lambda _name: None)
    monkeypatch.delenv("TELECLAUDE_SESSION_ID", raising=False)

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0  # Clean exit for standalone sessions
    assert not sent


def test_receiver_exits_cleanly_when_session_not_in_db(monkeypatch):
    """When env session ID doesn't exist in DB and recovery fails, exit cleanly."""
    from teleclaude.hooks import receiver

    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.setattr(receiver, "_get_parent_process_info", lambda: (123, "/dev/ttys001"))
    monkeypatch.setattr(receiver, "_session_exists", lambda _sid: False)
    monkeypatch.setattr(receiver, "_find_session_by_tmux_name", lambda _name: None)
    monkeypatch.setenv("TELECLAUDE_SESSION_ID", "sess-old")

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0  # Clean exit for standalone sessions
    assert not sent


def test_receiver_recovers_from_native_session_id(monkeypatch):
    from teleclaude.hooks import receiver

    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="codex", event_type='{"thread-id": "native-1"}')
    )
    monkeypatch.setattr(receiver, "_get_parent_process_info", lambda: (None, None))
    monkeypatch.setattr(receiver, "_find_session_by_native_id", lambda _sid: "sess-native")
    monkeypatch.delenv("TELECLAUDE_SESSION_ID", raising=False)

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "sess-native"
    assert event_type == "stop"


def test_receiver_maps_gemini_after_agent_to_stop(monkeypatch):
    from teleclaude.hooks import receiver

    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_normalize(_event_type, data):
        return data

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_get_adapter", lambda _agent: fake_normalize)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="after_agent"))
    monkeypatch.setattr(receiver, "_session_exists", lambda _sid: True)
    monkeypatch.setenv("TELECLAUDE_SESSION_ID", "sess-1")

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "sess-1"
    assert event_type == "stop"
