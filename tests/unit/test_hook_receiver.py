"""Unit tests for hook receiver error handling."""

import argparse
import os
from pathlib import Path

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.hooks import receiver
from teleclaude.hooks.adapters.models import NormalizedHookPayload


def test_receiver_emits_error_event_on_normalize_failure(monkeypatch, tmp_path):
    """Test that normalization exceptions emit error events and exit nonzero."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_normalize(_event_type, _data):
        raise ValueError("boom")

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_get_adapter", lambda _agent: fake_normalize)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))

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
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("TMUX", raising=False)  # Prevent tmux recovery from running

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0  # Clean exit for standalone sessions
    assert not sent


def test_receiver_exits_cleanly_when_tmux_recovery_fails(monkeypatch):
    """When tmux recovery fails, exit cleanly (standalone session)."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.delenv("TMPDIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0  # Clean exit for standalone sessions
    assert not sent


def test_receiver_exits_cleanly_when_session_not_in_db(monkeypatch):
    """When env session ID doesn't exist in DB and recovery fails, exit cleanly."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    monkeypatch.delenv("TMPDIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0  # Clean exit for standalone sessions
    assert not sent


def test_receiver_recovers_from_native_session_id(monkeypatch, tmp_path):
    """Test that missing env session is recovered from native session id."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="codex", event_type='{"thread-id": "native-1"}')
    )
    tmpdir = tmp_path / "tmp-native"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-native")
    monkeypatch.setenv("TMPDIR", str(tmpdir))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "sess-native"
    assert event_type == "stop"


def test_receiver_maps_gemini_after_agent_to_stop(monkeypatch, tmp_path):
    """Test that gemini after_agent is mapped to stop before enqueue."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_normalize(_event_type, _data):
        return NormalizedHookPayload()

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_get_adapter", lambda _agent: fake_normalize)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="after_agent"))
    tmpdir = tmp_path / "tmp-gemini"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "sess-1"
    assert event_type == "stop"


def test_receiver_includes_agent_name_in_payload(monkeypatch, tmp_path):
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_normalize(_event_type, _data):
        return NormalizedHookPayload()

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_get_adapter", lambda _agent: fake_normalize)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="stop"))
    tmpdir = tmp_path / "tmp-agent"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))

    receiver.main()

    assert sent
    _session_id, _event_type, data = sent[0]
    assert data["agent_name"] == "claude"
