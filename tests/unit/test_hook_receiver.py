"""Unit tests for hook receiver error handling."""

import argparse
import json
import os
import sqlite3

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.hooks import receiver


def test_receiver_emits_error_on_invalid_stdin_json(monkeypatch, tmp_path):
    """Invalid hook JSON should emit an error event and exit nonzero."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: (_ for _ in ()).throw(json.JSONDecodeError("bad", "{", 1)))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 1
    assert sent
    session_id, event_type, data = sent[0]
    assert session_id == "sess-1"
    assert event_type == "error"
    assert data["code"] == "HOOK_INVALID_JSON"
    assert data["source"] == "hook_receiver"


def test_receiver_exits_cleanly_without_session(monkeypatch):
    """Standalone sessions (not started via TeleClaude) should exit cleanly."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
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
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
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
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    monkeypatch.delenv("TMPDIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0  # Clean exit for standalone sessions
    assert not sent


def test_receiver_emits_error_on_deprecated_event_name(monkeypatch, tmp_path):
    """Legacy prompt/stop event names should produce a precise error event."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="prompt", cwd=None)
    )

    tmpdir = tmp_path / "tmp-deprecated"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-legacy")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 1
    assert sent
    session_id, event_type, data = sent[0]
    assert session_id == "sess-legacy"
    assert event_type == "error"
    assert data["code"] == "HOOK_EVENT_DEPRECATED"


def test_receiver_recovers_from_native_session_id(monkeypatch, tmp_path):
    """Test that missing env session is recovered from native session id."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_parse_args",
        lambda: argparse.Namespace(agent="codex", event_type='{"thread-id": "native-1"}', cwd=None),
    )
    tmpdir = tmp_path / "tmp-native"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-native")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "sess-native"
    assert event_type == "agent_stop"


def test_receiver_accepts_gemini_stop_event(monkeypatch, tmp_path):
    """Gemini agent_stop with prompt_response should emit internal agent_stop."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"prompt_response":"done"}',
            {"prompt_response": "done"},
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="agent_stop", cwd=None)
    )
    tmpdir = tmp_path / "tmp-gemini"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "sess-1"
    assert event_type == "agent_stop"


def test_receiver_updates_native_fields_for_gemini_session_start(monkeypatch, tmp_path):
    """Gemini session_start should include native fields in enqueued data."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id": "native-1", "transcript_path": "/tmp/gemini.jsonl"}',
            {
                "session_id": "native-1",
                "transcript_path": "/tmp/gemini.jsonl",
            },
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="session_start", cwd=None)
    )
    tmpdir = tmp_path / "tmp-gemini-start"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    assert sent
    _, _, data = sent[0]
    assert data["native_session_id"] == "native-1"
    assert data["native_log_file"] == "/tmp/gemini.jsonl"


def test_receiver_persists_native_fields_to_db(monkeypatch, tmp_path):
    """Hook receiver should persist native session fields to sessions table."""
    db_path = tmp_path / "teleclaude.db"

    from sqlalchemy import create_engine
    from sqlmodel import Session as SqlSession
    from sqlmodel import SQLModel

    from teleclaude.core import db_models as _models  # noqa: F811

    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with SqlSession(engine) as session:
        session.add(_models.Session(session_id="sess-1", computer_name="test"))
        session.commit()

    monkeypatch.setenv("TELECLAUDE_DB_PATH", str(db_path))
    monkeypatch.setattr(receiver, "_enqueue_hook_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id": "native-1", "transcript_path": "/tmp/native.jsonl"}',
            {"session_id": "native-1", "transcript_path": "/tmp/native.jsonl"},
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    tmpdir = tmp_path / "tmp-native"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT native_session_id, native_log_file FROM sessions WHERE session_id = ?", ("sess-1",)
        ).fetchone()
    assert row == ("native-1", "/tmp/native.jsonl")


def test_receiver_forwards_gemini_prompt_event(monkeypatch, tmp_path):
    """Gemini prompt should be forwarded as user_prompt_submit."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id": "native-2", "transcript_path": "/tmp/gemini-2.jsonl"}',
            {
                "session_id": "native-2",
                "transcript_path": "/tmp/gemini-2.jsonl",
            },
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="user_prompt_submit", cwd=None)
    )
    tmpdir = tmp_path / "tmp-gemini-prompt"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-2")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    assert sent
    session_id, event_type, data = sent[0]
    assert session_id == "sess-2"
    assert event_type == "user_prompt_submit"
    assert data["native_session_id"] == "native-2"
    assert data["native_log_file"] == "/tmp/gemini-2.jsonl"


def test_receiver_gemini_agent_stop_forwards_directly(monkeypatch, tmp_path):
    """Gemini agent_stop now forwards directly without splitting (BeforeAgent handles prompt)."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id":"native-9","transcript_path":"/tmp/g.json","prompt":"hi","prompt_response":"   "}',
            {
                "session_id": "native-9",
                "transcript_path": "/tmp/g.json",
                "prompt": "hi",
                "prompt_response": "   ",
            },
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="AfterAgent", cwd=None)
    )
    tmpdir = tmp_path / "tmp-gemini-empty-stop"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-9")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()
    assert len(sent) == 1
    session_id, event_type, data = sent[0]
    assert session_id == "sess-9"
    assert event_type == "agent_stop"  # AfterAgent maps to agent_stop


def test_receiver_gemini_before_agent_emits_user_prompt_submit(monkeypatch, tmp_path):
    """Gemini BeforeAgent hook should emit user_prompt_submit."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id":"native-10","transcript_path":"/tmp/g2.json","prompt":"user turn"}',
            {
                "session_id": "native-10",
                "transcript_path": "/tmp/g2.json",
                "prompt": "user turn",
            },
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="BeforeAgent", cwd=None)
    )
    tmpdir = tmp_path / "tmp-gemini-before-agent"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-10")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    assert len(sent) == 1
    assert sent[0][1] == "user_prompt_submit"


def test_receiver_includes_agent_name_in_payload(monkeypatch, tmp_path):
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    tmpdir = tmp_path / "tmp-agent"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("sess-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    assert sent
    _session_id, _event_type, data = sent[0]
    assert data["agent_name"] == "claude"


def test_receiver_prefers_tmux_session_id_over_session_map(monkeypatch, tmp_path):
    """TMUX session id must override headless session map resolution."""
    sent = []
    persisted = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_persist(agent, native_session_id, session_id):
        persisted.append((agent, native_session_id, session_id))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-1"}', {"session_id": "native-1"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "cached-1")
    monkeypatch.setattr(receiver, "_persist_session_map", fake_persist)
    tmpdir = tmp_path / "tmp-tmux"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("tmux-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "tmux-1"
    assert event_type == "agent_stop"
    assert persisted == []


def test_receiver_persists_session_map_for_headless(monkeypatch, tmp_path):
    """Headless hooks should persist to the global session map."""
    sent = []
    persisted = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_persist(agent, native_session_id, session_id):
        persisted.append((agent, native_session_id, session_id))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-2"}', {"session_id": "native-2"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: None)
    monkeypatch.setattr(receiver, "_find_session_id_by_native", lambda _native: None)
    monkeypatch.setattr(receiver, "_persist_session_map", fake_persist)
    monkeypatch.setattr(receiver.uuid, "uuid4", lambda: "headless-1")
    monkeypatch.delenv("TMPDIR", raising=False)

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "headless-1"
    assert event_type == "agent_stop"
    assert persisted == [("claude", "native-2", "headless-1")]


def test_receiver_refreshes_stale_env_session_id(monkeypatch, tmp_path):
    """When env session id is stale, receiver should refresh and persist new mapping."""
    sent = []
    persisted = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_persist(agent, native_session_id, session_id):
        persisted.append((agent, native_session_id, session_id))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_persist_session_map", fake_persist)
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: None)
    monkeypatch.setattr(
        receiver,
        "_resolve_or_refresh_session_id",
        lambda _candidate, _native, *, agent: "refreshed-1",  # noqa: ARG005
    )
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-3"}', {"session_id": "native-3"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="session_start", cwd=None)
    )

    tmpdir = tmp_path / "tmp-stale-env"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("stale-env-1")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "refreshed-1"
    assert event_type == "session_start"
    assert persisted == [("claude", "native-3", "refreshed-1")]


def test_receiver_ignores_legacy_marker_outside_teleclaude_tmp_base(monkeypatch, tmp_path):
    """Global TMPDIR markers must not override native->session map resolution."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "cached-1")
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-4"}', {"session_id": "native-4"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )

    tmpdir = tmp_path / "global-tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "teleclaude_session_id").write_text("stale-global-marker")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "teleclaude-sessions"))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "cached-1"
    assert event_type == "agent_stop"
