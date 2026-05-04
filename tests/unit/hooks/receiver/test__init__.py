"""Focused tests for teleclaude.hooks.receiver checkpoint wiring."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session as SqlSession
from sqlmodel import SQLModel, select

from teleclaude.core import db_models
from teleclaude.core.db.connection_factory import create_sync_db_engine
from teleclaude.core.events import AgentHookEvents
from teleclaude.hooks.receiver import (
    _handle_user_prompt_submit,
    _maybe_checkpoint_output,
    _resolve_checkpoint_project_path,
    enqueue_hook_event,
)


def _make_outbox_db(tmp_path: Path) -> str:
    db_path = tmp_path / "outbox.sqlite"
    engine = create_sync_db_engine(db_path)
    SQLModel.metadata.create_all(engine, tables=[db_models.HookOutbox.__table__])
    return str(db_path)


def test_enqueue_hook_event_debounces_recent_unclaimed_row_latest_wins(tmp_path: Path) -> None:
    outbox_db = _make_outbox_db(tmp_path)

    enqueue_hook_event(
        "session-1",
        "agent_stop",
        {"message": "first"},
        outbox_db=outbox_db,
        latest_wins_within_s=10.0,
    )
    enqueue_hook_event(
        "session-1",
        "agent_stop",
        {"message": "latest"},
        outbox_db=outbox_db,
        latest_wins_within_s=10.0,
    )

    with SqlSession(create_sync_db_engine(outbox_db)) as session:
        rows = session.exec(select(db_models.HookOutbox)).all()

    assert len(rows) == 1
    assert json.loads(rows[0].payload) == {"message": "latest"}
    assert rows[0].attempt_count == 0
    assert rows[0].locked_at is None


def test_enqueue_hook_event_does_not_replace_locked_recent_row(tmp_path: Path) -> None:
    outbox_db = _make_outbox_db(tmp_path)

    enqueue_hook_event(
        "session-1",
        "agent_stop",
        {"message": "first"},
        outbox_db=outbox_db,
        latest_wins_within_s=10.0,
    )

    engine = create_sync_db_engine(outbox_db)
    with SqlSession(engine) as session:
        row = session.exec(select(db_models.HookOutbox)).first()
        assert row is not None
        row.locked_at = datetime.now(UTC).isoformat()
        session.add(row)
        session.commit()

    enqueue_hook_event(
        "session-1",
        "agent_stop",
        {"message": "latest"},
        outbox_db=outbox_db,
        latest_wins_within_s=10.0,
    )

    with SqlSession(engine) as session:
        rows = session.exec(select(db_models.HookOutbox).order_by(db_models.HookOutbox.id)).all()

    assert len(rows) == 2
    assert json.loads(rows[0].payload) == {"message": "first"}
    assert json.loads(rows[1].payload) == {"message": "latest"}


def test_checkpoint_wiring_threads_session_id_into_checkpoint_builder() -> None:
    row = SimpleNamespace(
        native_log_file="/tmp/session.jsonl",
        native_session_id="native-1",
        working_slug="demo-slug",
        project_path="/repo",
        last_message_sent_at=datetime(2026, 4, 11, 10, 0, tzinfo=UTC),
        last_checkpoint_at=None,
    )

    with (
        patch("teleclaude.hooks.receiver.is_checkpoint_disabled", return_value=False),
        patch("teleclaude.hooks.receiver.consume_checkpoint_flag", return_value=False),
        patch("teleclaude.hooks.receiver._load_checkpoint_row", return_value=row),
        patch("teleclaude.hooks.receiver.get_checkpoint_content", return_value="checkpoint") as checkpoint_mock,
        patch("teleclaude.hooks.receiver.enqueue_checkpoint_seen"),
    ):
        result = _maybe_checkpoint_output(
            "session-1",
            "codex",
            {},
            outbox_db="/tmp/outbox.sqlite",
        )

    assert result == "checkpoint"
    assert checkpoint_mock.call_args.kwargs["session_id"] == "session-1"


class TestResolveCheckpointProjectPath:
    @pytest.mark.unit
    def test_worktree_session_resolves_to_worktree_path(self) -> None:
        """Worktree sessions must resolve to the actual worktree dir, not repo root.

        Without this, _current_branch runs against the repo root (always main)
        and main_only checkpoint actions fire incorrectly in worktrees.
        """
        row = SimpleNamespace(
            project_path="/repo",
            subdir="trees/my-feature",
            native_log_file=None,
        )
        assert _resolve_checkpoint_project_path(row) == "/repo/trees/my-feature"

    @pytest.mark.unit
    def test_repo_root_session_returns_project_path_unchanged(self) -> None:
        row = SimpleNamespace(
            project_path="/repo",
            subdir=None,
            native_log_file=None,
        )
        assert _resolve_checkpoint_project_path(row) == "/repo"

    @pytest.mark.unit
    def test_empty_subdir_returns_project_path_unchanged(self) -> None:
        row = SimpleNamespace(
            project_path="/repo",
            subdir="",
            native_log_file=None,
        )
        assert _resolve_checkpoint_project_path(row) == "/repo"


def test_handle_user_prompt_submit_drops_xml_wrapped_internal_prompt() -> None:
    dropped = _handle_user_prompt_submit(
        AgentHookEvents.USER_PROMPT_SUBMIT,
        {
            "prompt": '<hook_prompt hook_run_id="stop:2:/Users/Morriz/.codex/hooks.json">[TeleClaude Checkpoint] - Context-aware checkpoint'
        },
        "codex",
        "session-1",
        "native-1",
    )

    assert dropped is True
