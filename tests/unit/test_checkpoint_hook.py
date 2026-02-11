"""Unit tests for hook-based invisible checkpoint logic in receiver.py."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.hooks import receiver

TEST_PROJECT_PATH = str(Path(__file__).resolve().parents[2])


@pytest.fixture()
def db_with_session(tmp_path, monkeypatch):
    """Create an in-memory-like SQLite DB with a single session row.

    Returns a helper that creates a session with configurable timestamps.
    """
    db_path = tmp_path / "teleclaude.db"

    from sqlalchemy import create_engine
    from sqlmodel import Session as SqlSession
    from sqlmodel import SQLModel

    from teleclaude.core import db_models

    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    monkeypatch.setenv("TELECLAUDE_DB_PATH", str(db_path))

    # Patch _create_sync_engine to use our test engine
    monkeypatch.setattr(receiver, "_create_sync_engine", lambda: engine)

    def _create(
        session_id: str = "sess-1",
        last_message_sent_at: datetime | None = None,
        last_checkpoint_at: datetime | None = None,
        project_path: str | None = TEST_PROJECT_PATH,
        native_log_file: str | None = None,
    ):
        with SqlSession(engine) as session:
            row = db_models.Session(
                session_id=session_id,
                computer_name="test",
                last_message_sent_at=last_message_sent_at,
                last_checkpoint_at=last_checkpoint_at,
                project_path=project_path,
                native_log_file=native_log_file,
            )
            session.add(row)
            session.commit()
        return engine

    return _create


def test_stop_hook_active_returns_none():
    """Claude's stop_hook_active escape hatch should bypass checkpoint."""
    result = receiver._maybe_checkpoint_output("sess-1", "claude", {"stop_hook_active": True})
    assert result is None


def test_no_session_returns_none(db_with_session):
    """Missing session row should return None (fail-open)."""
    db_with_session()  # creates sess-1
    result = receiver._maybe_checkpoint_output("nonexistent", "claude", {})
    assert result is None


def test_no_turn_start_returns_none(db_with_session):
    """Session with no timestamps should skip checkpoint."""
    db_with_session(last_message_sent_at=None, last_checkpoint_at=None)
    result = receiver._maybe_checkpoint_output("sess-1", "claude", {})
    assert result is None


def test_elapsed_below_threshold_returns_none(db_with_session):
    """Elapsed time under 30s should skip checkpoint."""
    now = datetime.now(timezone.utc)
    db_with_session(last_message_sent_at=now - timedelta(seconds=10))
    result = receiver._maybe_checkpoint_output("sess-1", "claude", {})
    assert result is None


def test_elapsed_above_threshold_claude(db_with_session):
    """Elapsed > 30s for Claude should return blocking JSON."""
    now = datetime.now(timezone.utc)
    engine = db_with_session(last_message_sent_at=now - timedelta(seconds=60))

    result = receiver._maybe_checkpoint_output("sess-1", "claude", {})
    assert result is not None

    parsed = json.loads(result)
    assert parsed["decision"] == "block"
    assert isinstance(parsed["reason"], str)
    assert len(parsed["reason"]) > 0

    # Verify DB was updated with last_checkpoint_at
    from sqlmodel import Session as SqlSession

    from teleclaude.core import db_models

    with SqlSession(engine) as session:
        row = session.get(db_models.Session, "sess-1")
        assert row is not None
        assert row.last_checkpoint_at is not None


def test_elapsed_above_threshold_gemini(db_with_session):
    """Elapsed > 30s for Gemini should return deny JSON."""
    now = datetime.now(timezone.utc)
    db_with_session(last_message_sent_at=now - timedelta(seconds=60))

    result = receiver._maybe_checkpoint_output("sess-1", "gemini", {})
    assert result is not None

    parsed = json.loads(result)
    assert parsed["decision"] == "deny"
    assert isinstance(parsed["reason"], str)
    assert len(parsed["reason"]) > 0


def test_checkpoint_skips_when_context_builder_returns_none(db_with_session, monkeypatch):
    """No-op checkpoint payload should not block or update checkpoint timestamp."""
    now = datetime.now(timezone.utc)
    engine = db_with_session(last_message_sent_at=now - timedelta(seconds=60))

    monkeypatch.setattr("teleclaude.hooks.checkpoint.get_checkpoint_content", lambda **_kwargs: None)
    result = receiver._maybe_checkpoint_output("sess-1", "claude", {})
    assert result is None

    from sqlmodel import Session as SqlSession

    from teleclaude.core import db_models

    with SqlSession(engine) as session:
        row = session.get(db_models.Session, "sess-1")
        assert row is not None
        assert row.last_checkpoint_at is None


def test_codex_returns_none(db_with_session):
    """Codex has no hook mechanism; should always return None."""
    now = datetime.now(timezone.utc)
    engine = db_with_session(last_message_sent_at=now - timedelta(seconds=60))

    result = receiver._maybe_checkpoint_output("sess-1", "codex", {})
    assert result is None

    # Ensure codex hook path does not mutate checkpoint timestamp.
    from sqlmodel import Session as SqlSession

    from teleclaude.core import db_models

    with SqlSession(engine) as session:
        row = session.get(db_models.Session, "sess-1")
        assert row is not None
        assert row.last_checkpoint_at is None


def test_checkpoint_uses_most_recent_timestamp(db_with_session):
    """Turn start should be max(message_at, checkpoint_at)."""
    now = datetime.now(timezone.utc)
    # Message was 60s ago, but checkpoint was 10s ago — should skip
    db_with_session(
        last_message_sent_at=now - timedelta(seconds=60),
        last_checkpoint_at=now - timedelta(seconds=10),
    )

    result = receiver._maybe_checkpoint_output("sess-1", "claude", {})
    assert result is None


def test_checkpoint_fires_when_checkpoint_at_is_old(db_with_session):
    """When last_checkpoint_at is old enough, should fire again."""
    now = datetime.now(timezone.utc)
    db_with_session(
        last_message_sent_at=now - timedelta(seconds=120),
        last_checkpoint_at=now - timedelta(seconds=45),
    )

    result = receiver._maybe_checkpoint_output("sess-1", "claude", {})
    assert result is not None
    parsed = json.loads(result)
    assert parsed["decision"] == "block"


def test_checkpoint_prefers_session_project_path_over_transcript_workdir(db_with_session, monkeypatch):
    now = datetime.now(timezone.utc)
    db_with_session(
        last_message_sent_at=now - timedelta(seconds=60),
        project_path="/tmp/project-from-session",
        native_log_file="/tmp/transcript.jsonl",
    )

    called: dict[str, str | None] = {"project_path": None}

    def _fake_get_checkpoint_content(transcript_path, agent_name, project_path, working_slug=None):
        called["project_path"] = project_path
        return "checkpoint"

    monkeypatch.setattr("teleclaude.hooks.checkpoint.get_checkpoint_content", _fake_get_checkpoint_content)
    monkeypatch.setattr(
        "teleclaude.utils.transcript.extract_workdir_from_transcript",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("should not read transcript workdir when project_path exists")
        ),
    )

    result = receiver._maybe_checkpoint_output("sess-1", "claude", {})
    assert result is not None
    assert called["project_path"] == "/tmp/project-from-session"


def test_checkpoint_falls_back_to_transcript_workdir_when_project_path_missing(db_with_session, monkeypatch):
    now = datetime.now(timezone.utc)
    db_with_session(
        last_message_sent_at=now - timedelta(seconds=60),
        project_path=None,
        native_log_file="/tmp/transcript.jsonl",
    )

    called: dict[str, str | None] = {"project_path": None}

    def _fake_get_checkpoint_content(transcript_path, agent_name, project_path, working_slug=None):
        called["project_path"] = project_path
        return "checkpoint"

    monkeypatch.setattr("teleclaude.hooks.checkpoint.get_checkpoint_content", _fake_get_checkpoint_content)
    monkeypatch.setattr(
        "teleclaude.utils.transcript.extract_workdir_from_transcript",
        lambda _path: "/tmp/project-from-transcript",
    )

    result = receiver._maybe_checkpoint_output("sess-1", "claude", {})
    assert result is not None
    assert called["project_path"] == "/tmp/project-from-transcript"
