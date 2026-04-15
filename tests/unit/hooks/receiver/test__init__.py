# guard: no-companion
"""Focused tests for teleclaude.hooks.receiver checkpoint wiring."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from teleclaude.hooks.receiver import _maybe_checkpoint_output


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
