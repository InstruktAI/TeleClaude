"""Characterization tests for teleclaude.core.codex_transcript."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.codex_transcript import (
    HookTranscriptMetadata,
    discover_codex_transcript_family,
    discover_codex_transcript_family_meta,
    discover_codex_transcript_path,
    discover_current_codex_transcript_path,
    is_codex_subagent_transcript,
    read_codex_transcript_meta,
    resolve_hook_transcript_metadata,
    should_persist_codex_native_metadata,
)


class TestDiscoverCodexTranscriptPath:
    @pytest.mark.unit
    def test_empty_session_id_returns_none(self):
        result = discover_codex_transcript_path("")
        assert result is None

    @pytest.mark.unit
    def test_none_equivalent_empty_returns_none(self):
        # native_session_id=None would typically not be passed, but empty string is the guard
        result = discover_codex_transcript_path("")
        assert result is None

    @pytest.mark.unit
    def test_no_sessions_dir_returns_none(self, tmp_path: Path) -> None:
        with patch("teleclaude.core.codex_transcript.Path.home", return_value=tmp_path):
            result = discover_codex_transcript_path("abc-123")
        assert result is None

    @pytest.mark.unit
    def test_finds_transcript_in_todays_dir(self, tmp_path: Path) -> None:
        from datetime import datetime

        today = datetime.now()
        date_dir = tmp_path / ".codex" / "sessions" / str(today.year) / f"{today.month:02d}" / f"{today.day:02d}"
        date_dir.mkdir(parents=True)
        transcript = date_dir / "rollout-2024-01-01-abc-123.jsonl"
        transcript.write_text("{}")

        with patch("teleclaude.core.codex_transcript.Path.home", return_value=tmp_path):
            result = discover_codex_transcript_path("abc-123")

        assert result == str(transcript)

    @pytest.mark.unit
    def test_returns_none_when_no_matching_file(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".codex" / "sessions"
        sessions_dir.mkdir(parents=True)

        with patch("teleclaude.core.codex_transcript.Path.home", return_value=tmp_path):
            result = discover_codex_transcript_path("nonexistent-session")

        assert result is None


class TestCodexSubagentDetection:
    @pytest.mark.unit
    def test_discovers_current_transcript_from_codex_thread_id(self):
        with (
            patch.dict("os.environ", {"CODEX_THREAD_ID": "thread-123"}, clear=False),
            patch("teleclaude.core.codex_transcript.discover_codex_transcript_path", return_value="/tmp/current.jsonl"),
        ):
            assert discover_current_codex_transcript_path() == "/tmp/current.jsonl"

    @pytest.mark.unit
    def test_detects_subagent_transcript_from_session_meta(self, tmp_path: Path) -> None:
        transcript = tmp_path / "rollout-subagent.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {"source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        assert is_codex_subagent_transcript(str(transcript)) is True

    @pytest.mark.unit
    def test_reads_codex_transcript_meta(self, tmp_path: Path) -> None:
        transcript = tmp_path / "rollout-parent.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-20T07:19:10.235Z",
                    "type": "session_meta",
                    "payload": {"id": "parent-thread", "timestamp": "2026-03-20T07:19:10.144Z", "source": {}},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        meta = read_codex_transcript_meta(transcript)

        assert meta is not None
        assert meta.transcript_path == str(transcript)
        assert meta.thread_id == "parent-thread"
        assert meta.parent_thread_id is None
        assert meta.session_started_at == datetime(2026, 3, 20, 7, 19, 10, 235000, tzinfo=UTC)

    @pytest.mark.unit
    def test_discovers_codex_transcript_family_recursively(self, tmp_path: Path) -> None:
        from datetime import datetime

        today = datetime.now()
        date_dir = tmp_path / ".codex" / "sessions" / str(today.year) / f"{today.month:02d}" / f"{today.day:02d}"
        date_dir.mkdir(parents=True)

        parent = date_dir / "rollout-parent-thread.jsonl"
        child = date_dir / "rollout-child-thread.jsonl"
        grandchild = date_dir / "rollout-grandchild-thread.jsonl"
        sibling = date_dir / "rollout-sibling-thread.jsonl"
        unrelated = date_dir / "rollout-unrelated-thread.jsonl"

        parent.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": "parent-thread", "source": {}}}) + "\n",
            encoding="utf-8",
        )
        child.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "child-thread",
                        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent-thread"}}},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        grandchild.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "grandchild-thread",
                        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "child-thread"}}},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        sibling.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "sibling-thread",
                        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent-thread"}}},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        unrelated.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "unrelated-thread",
                        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "other-thread"}}},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        with patch("teleclaude.core.codex_transcript.Path.home", return_value=tmp_path):
            family = discover_codex_transcript_family(root_transcript_path=str(parent))

        assert family[0] == str(parent)
        assert set(family) == {str(parent), str(child), str(grandchild), str(sibling)}
        assert str(unrelated) not in family

    @pytest.mark.unit
    def test_discovers_codex_transcript_family_meta_with_timestamps(self, tmp_path: Path) -> None:
        from datetime import datetime

        today = datetime.now()
        date_dir = tmp_path / ".codex" / "sessions" / str(today.year) / f"{today.month:02d}" / f"{today.day:02d}"
        date_dir.mkdir(parents=True)

        parent = date_dir / "rollout-parent-thread.jsonl"
        child = date_dir / "rollout-child-thread.jsonl"
        parent.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-20T07:19:10.235Z",
                    "type": "session_meta",
                    "payload": {"id": "parent-thread", "source": {}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        child.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-20T07:21:10.235Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "child-thread",
                        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent-thread"}}},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        with patch("teleclaude.core.codex_transcript.Path.home", return_value=tmp_path):
            family = discover_codex_transcript_family_meta(root_transcript_path=str(parent))

        assert [meta.transcript_path for meta in family] == [str(parent), str(child)]
        assert family[0].session_started_at == datetime(2026, 3, 20, 7, 19, 10, 235000, tzinfo=UTC)
        assert family[1].session_started_at == datetime(2026, 3, 20, 7, 21, 10, 235000, tzinfo=UTC)

    @pytest.mark.unit
    def test_should_persist_native_metadata_for_non_subagent_transcript(self, tmp_path: Path) -> None:
        transcript = tmp_path / "rollout-parent.jsonl"
        transcript.write_text(json.dumps({"type": "session_meta", "payload": {"source": {}}}) + "\n", encoding="utf-8")

        assert (
            should_persist_codex_native_metadata(
                native_log_file=str(transcript),
                native_session_id="native-1",
            )
            is True
        )

    @pytest.mark.unit
    def test_should_skip_persist_for_provided_subagent_transcript(self, tmp_path: Path) -> None:
        transcript = tmp_path / "rollout-child.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {"source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        assert (
            should_persist_codex_native_metadata(
                native_log_file=str(transcript),
                native_session_id="child-native",
            )
            is False
        )

    @pytest.mark.unit
    def test_should_persist_when_no_transcript_is_provided(self) -> None:
        assert (
            should_persist_codex_native_metadata(
                native_log_file=None,
                native_session_id="child-native",
            )
            is True
        )

    @pytest.mark.unit
    def test_resolve_hook_transcript_metadata_does_not_discover_missing_codex_path(self) -> None:
        with patch("teleclaude.core.codex_transcript.discover_codex_transcript_path") as discover_mock:
            result = resolve_hook_transcript_metadata(
                session_id="sess-1",
                event_type="agent_stop",
                data={"native_session_id": "native-child"},
                normalized_agent_name="codex",
            )

        assert result == HookTranscriptMetadata(
            transcript_path=None,
            native_session_id="native-child",
            native_log_file=None,
            is_codex_subagent=False,
        )
        discover_mock.assert_not_called()
