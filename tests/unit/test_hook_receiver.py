"""Unit tests for hook receiver error handling."""

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.hooks import receiver
from teleclaude.hooks.checkpoint_flags import CHECKPOINT_CLEAR_FLAG, CHECKPOINT_RECHECK_FLAG, checkpoint_flag_path


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
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 1
    assert sent == []


def test_receiver_exits_cleanly_without_session(monkeypatch):
    """Unresolved hook sessions should be silently dropped."""
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

    assert exc.value.code == 0
    assert not sent


def test_receiver_exits_cleanly_when_tmux_recovery_fails(monkeypatch):
    """When session resolution fails, receiver should drop cleanly."""
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

    assert exc.value.code == 0
    assert not sent


def test_receiver_exits_cleanly_when_session_not_in_db(monkeypatch):
    """When env session ID doesn't resolve, receiver should drop cleanly."""
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

    assert exc.value.code == 0
    assert not sent


def test_receiver_emits_error_on_deprecated_event_name(monkeypatch, tmp_path):
    """Unknown event names should be dropped silently."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="prompt", cwd=None)
    )

    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0
    assert sent == []


def test_receiver_unhandled_event_drops_cleanly(monkeypatch, tmp_path):
    """Unhandled hook event types should be dropped cleanly."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="after_model", cwd=None)
    )
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0
    assert sent == []


def test_receiver_recovers_from_native_session_map(monkeypatch, tmp_path):
    """Native session map should resolve the TeleClaude session for non-session_start hooks."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_parse_args",
        lambda: argparse.Namespace(agent="codex", event_type='{"thread-id": "native-1"}', cwd=None),
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-native")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

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
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-1")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

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
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

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
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-1")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT native_session_id, native_log_file FROM sessions WHERE session_id = ?", ("sess-1",)
        ).fetchone()
    assert row == ("native-1", "/tmp/native.jsonl")


def test_receiver_logs_native_log_rotation(monkeypatch, tmp_path, caplog):
    """When transcript path changes mid-session, receiver should persist and log it."""
    db_path = tmp_path / "teleclaude.db"

    from sqlalchemy import create_engine
    from sqlmodel import Session as SqlSession
    from sqlmodel import SQLModel

    from teleclaude.core import db_models as _models  # noqa: F811

    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with SqlSession(engine) as session:
        session.add(
            _models.Session(
                session_id="sess-1",
                computer_name="test",
                native_session_id="native-1",
                native_log_file="/tmp/old-native.jsonl",
            )
        )
        session.commit()

    monkeypatch.setenv("TELECLAUDE_DB_PATH", str(db_path))
    monkeypatch.setattr(receiver, "_enqueue_hook_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(receiver, "_maybe_checkpoint_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id": "native-1", "transcript_path": "/tmp/new-native.jsonl", "prompt_response":"ok"}',
            {"session_id": "native-1", "transcript_path": "/tmp/new-native.jsonl", "prompt_response": "ok"},
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="agent_stop", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-1")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    caplog.set_level("INFO")
    receiver.main()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT native_session_id, native_log_file FROM sessions WHERE session_id = ?", ("sess-1",)
        ).fetchone()
    assert row == ("native-1", "/tmp/new-native.jsonl")
    assert any("Native session metadata changed" in rec.message for rec in caplog.records)


def test_checkpoint_output_handles_mixed_timezone_timestamps(monkeypatch, tmp_path):
    """Checkpoint evaluation must not crash on mixed aware/naive DB timestamps."""
    from sqlalchemy import create_engine
    from sqlmodel import SQLModel

    db_path = tmp_path / "teleclaude.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    now = datetime.now(timezone.utc)
    message_at = (now - timedelta(seconds=120)).isoformat()
    checkpoint_at = (now - timedelta(seconds=5)).replace(tzinfo=None).isoformat(sep=" ")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, computer_name, last_input_origin, last_message_sent_at, last_checkpoint_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("sess-mixed-tz", "test", "telegram", message_at, checkpoint_at),
        )
        conn.commit()

    monkeypatch.setattr(receiver, "_create_sync_engine", lambda: engine)

    # Recent checkpoint_at should win over old message_at and skip re-checkpoint.
    assert receiver._maybe_checkpoint_output("sess-mixed-tz", "gemini", {}) is None


def test_checkpoint_output_clear_flag_skips_block(monkeypatch, tmp_path):
    """Clear marker should short-circuit checkpoint blocking for the resolved session."""
    from sqlalchemy import create_engine
    from sqlmodel import SQLModel

    db_path = tmp_path / "teleclaude.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    now = datetime.now(timezone.utc)
    message_at = (now - timedelta(seconds=120)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, computer_name, last_input_origin, last_message_sent_at)"
            " VALUES (?, ?, ?, ?)",
            ("sess-clear", "test", "telegram", message_at),
        )
        conn.commit()

    monkeypatch.setattr(receiver, "_create_sync_engine", lambda: engine)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    clear_path = checkpoint_flag_path("sess-clear", CHECKPOINT_CLEAR_FLAG)
    clear_path.parent.mkdir(parents=True, exist_ok=True)
    clear_path.touch()

    calls = {"count": 0}

    def _should_not_run(*_args, **_kwargs):
        calls["count"] += 1
        return "unexpected"

    monkeypatch.setattr("teleclaude.hooks.checkpoint.get_checkpoint_content", _should_not_run)

    result = receiver._maybe_checkpoint_output("sess-clear", "claude", {})
    assert result is None
    assert calls["count"] == 0
    assert clear_path.exists()


def test_checkpoint_output_stop_hook_active_blocks_once_then_allows(monkeypatch, tmp_path):
    """stop_hook_active should allow at most one additional checkpoint block."""
    from sqlalchemy import create_engine
    from sqlmodel import SQLModel

    db_path = tmp_path / "teleclaude.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    now = datetime.now(timezone.utc)
    message_at = (now - timedelta(seconds=120)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, computer_name, last_input_origin, last_message_sent_at)"
            " VALUES (?, ?, ?, ?)",
            ("sess-recheck", "test", "telegram", message_at),
        )
        conn.commit()

    monkeypatch.setattr(receiver, "_create_sync_engine", lambda: engine)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    calls = {"count": 0}

    def _fake_checkpoint(*_args, **_kwargs):
        calls["count"] += 1
        return "checkpoint"

    monkeypatch.setattr("teleclaude.hooks.checkpoint.get_checkpoint_content", _fake_checkpoint)

    first = receiver._maybe_checkpoint_output("sess-recheck", "claude", {"stop_hook_active": True})
    assert first == json.dumps({"decision": "block", "reason": "checkpoint"})
    assert calls["count"] == 1

    recheck_path = checkpoint_flag_path("sess-recheck", CHECKPOINT_RECHECK_FLAG)
    assert recheck_path.exists()

    second = receiver._maybe_checkpoint_output("sess-recheck", "claude", {"stop_hook_active": True})
    assert second is None
    assert calls["count"] == 1
    assert not recheck_path.exists()


def test_receiver_agent_stop_checkpoint_failure_fails_open(monkeypatch, tmp_path):
    """Checkpoint failures should never crash hook receiver or block enqueue."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver, "_maybe_checkpoint_output", lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("boom"))
    )
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id":"native-12","transcript_path":"/tmp/g4.json"}',
            {"session_id": "native-12", "transcript_path": "/tmp/g4.json"},
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="AfterAgent", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-12")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    assert len(sent) == 1
    assert sent[0][0] == "sess-12"
    assert sent[0][1] == "agent_stop"


def test_receiver_user_prompt_submit_resets_checkpoint_flags_tmux(monkeypatch, tmp_path):
    """Real user_prompt_submit should clear checkpoint escape markers for tmux sessions."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: ('{"session_id":"native-20","prompt":"hello"}', {"session_id": "native-20", "prompt": "hello"}),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="user_prompt_submit", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-20")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    clear_path = checkpoint_flag_path("sess-20", CHECKPOINT_CLEAR_FLAG)
    recheck_path = checkpoint_flag_path("sess-20", CHECKPOINT_RECHECK_FLAG)
    clear_path.parent.mkdir(parents=True, exist_ok=True)
    clear_path.touch()
    recheck_path.touch()

    receiver.main()

    assert sent
    assert sent[0][0] == "sess-20"
    assert sent[0][1] == "user_prompt_submit"
    assert clear_path.exists()
    assert not recheck_path.exists()


def test_receiver_user_prompt_submit_resets_checkpoint_flags_headless(monkeypatch, tmp_path):
    """Headless session resolution via native map should clear checkpoint markers too."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id":"native-headless-1","prompt":"hello"}',
            {"session_id": "native-headless-1", "prompt": "hello"},
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="user_prompt_submit", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "headless-1")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    clear_path = checkpoint_flag_path("headless-1", CHECKPOINT_CLEAR_FLAG)
    recheck_path = checkpoint_flag_path("headless-1", CHECKPOINT_RECHECK_FLAG)
    clear_path.parent.mkdir(parents=True, exist_ok=True)
    clear_path.touch()
    recheck_path.touch()

    receiver.main()

    assert sent
    assert sent[0][0] == "headless-1"
    assert sent[0][1] == "user_prompt_submit"
    assert clear_path.exists()
    assert not recheck_path.exists()


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
            '{"session_id": "native-2", "transcript_path": "/tmp/gemini-2.jsonl", "prompt":"hello"}',
            {
                "session_id": "native-2",
                "transcript_path": "/tmp/gemini-2.jsonl",
                "prompt": "hello",
            },
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="user_prompt_submit", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-2")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

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
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-9")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

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
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-10")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    assert len(sent) == 1
    assert sent[0][1] == "user_prompt_submit"


def test_receiver_gemini_before_agent_empty_prompt_is_dropped(monkeypatch, tmp_path):
    """Gemini BeforeAgent with empty prompt should not enqueue user_prompt_submit."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(
        receiver,
        "_read_stdin",
        lambda: (
            '{"session_id":"native-11","transcript_path":"/tmp/g3.json","prompt":""}',
            {
                "session_id": "native-11",
                "transcript_path": "/tmp/g3.json",
                "prompt": "",
                "hook_event_name": "BeforeAgent",
            },
        ),
    )
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="BeforeAgent", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "sess-11")
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    assert sent == []


def test_receiver_includes_agent_name_in_payload(monkeypatch, tmp_path):
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ("{}", {}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0
    assert sent == []


def test_receiver_uses_session_map_for_agent_stop(monkeypatch, tmp_path):
    """Agent stop should resolve via native session map."""
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
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "cached-1"
    assert event_type == "agent_stop"
    assert persisted == [("claude", "native-1", "cached-1")]


def test_receiver_drops_agent_stop_without_existing_mapping(monkeypatch, tmp_path):
    """Agent stop with unresolved mapping should be dropped cleanly."""
    sent = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-2"}', {"session_id": "native-2"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: None)
    monkeypatch.setattr(receiver, "_find_session_id_by_native", lambda _native: None)
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    with pytest.raises(SystemExit) as exc:
        receiver.main()

    assert exc.value.code == 0
    assert sent == []


def test_receiver_mints_session_on_session_start_when_unmapped(monkeypatch, tmp_path):
    """Session start should mint and persist mapping when native identity is new."""
    sent = []
    persisted = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_persist(agent, native_session_id, session_id):
        persisted.append((agent, native_session_id, session_id))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_persist_session_map", fake_persist)
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: None)
    monkeypatch.setattr(receiver, "_find_session_id_by_native", lambda _native: None)
    monkeypatch.setattr(receiver.uuid, "uuid4", lambda: "minted-1")
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-3"}', {"session_id": "native-3"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="session_start", cwd=None)
    )
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "minted-1"
    assert event_type == "session_start"
    assert persisted == [("claude", "native-3", "minted-1")]


def test_receiver_session_start_uses_env_session_id_over_mint(monkeypatch, tmp_path):
    """session_start should bind to existing TeleClaude session from TMPDIR marker."""
    sent = []
    persisted = []
    session_tmp = tmp_path / "session-1"
    session_tmp.mkdir(parents=True, exist_ok=True)
    (session_tmp / "teleclaude_session_id").write_text("env-sess-1", encoding="utf-8")

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_persist(agent, native_session_id, session_id):
        persisted.append((agent, native_session_id, session_id))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_persist_session_map", fake_persist)
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: None)
    monkeypatch.setattr(receiver, "_find_session_id_by_native", lambda _native: None)
    monkeypatch.setattr(receiver, "_is_active_session", lambda session_id: session_id == "env-sess-1")
    monkeypatch.setattr(receiver.uuid, "uuid4", lambda: "minted-should-not-be-used")
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-5"}', {"session_id": "native-5"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="session_start", cwd=None)
    )
    monkeypatch.setenv("TMPDIR", str(session_tmp.resolve()))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "env-sess-1"
    assert event_type == "session_start"
    assert persisted == [("claude", "native-5", "env-sess-1")]


def test_receiver_session_start_env_overrides_stale_cached_mapping(monkeypatch, tmp_path):
    """session_start should prefer env session id even when map has stale value."""
    sent = []
    persisted = []
    session_tmp = tmp_path / "session-2"
    session_tmp.mkdir(parents=True, exist_ok=True)
    (session_tmp / "teleclaude_session_id").write_text("env-sess-2", encoding="utf-8")

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_persist(agent, native_session_id, session_id):
        persisted.append((agent, native_session_id, session_id))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_persist_session_map", fake_persist)
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: "stale-sess")
    monkeypatch.setattr(receiver, "_resolve_or_refresh_session_id", lambda candidate, _native, agent: candidate)
    monkeypatch.setattr(receiver, "_is_active_session", lambda session_id: session_id == "env-sess-2")
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-6"}', {"session_id": "native-6"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="gemini", event_type="session_start", cwd=None)
    )
    monkeypatch.setenv("TMPDIR", str(session_tmp.resolve()))
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "env-sess-2"
    assert event_type == "session_start"
    assert persisted == [("gemini", "native-6", "env-sess-2")]


def test_receiver_uses_db_native_lookup_when_map_misses(monkeypatch, tmp_path):
    """Receiver should recover from DB native lookup and repersist map."""
    sent = []
    persisted = []

    def fake_enqueue(session_id, event_type, data):
        sent.append((session_id, event_type, data))

    def fake_persist(agent, native_session_id, session_id):
        persisted.append((agent, native_session_id, session_id))

    monkeypatch.setattr(receiver, "_enqueue_hook_event", fake_enqueue)
    monkeypatch.setattr(receiver, "_get_cached_session_id", lambda _agent, _native: None)
    monkeypatch.setattr(receiver, "_find_session_id_by_native", lambda _native: "db-1")
    monkeypatch.setattr(receiver, "_persist_session_map", fake_persist)
    monkeypatch.setattr(receiver, "_read_stdin", lambda: ('{"session_id": "native-4"}', {"session_id": "native-4"}))
    monkeypatch.setattr(
        receiver, "_parse_args", lambda: argparse.Namespace(agent="claude", event_type="agent_stop", cwd=None)
    )
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path.resolve()))

    receiver.main()

    assert sent
    session_id, event_type, _data = sent[0]
    assert session_id == "db-1"
    assert event_type == "agent_stop"
    assert persisted == [("claude", "native-4", "db-1")]
