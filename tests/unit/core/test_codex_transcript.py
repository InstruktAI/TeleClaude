"""Characterization tests for teleclaude.core.codex_transcript."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.core.codex_transcript import discover_codex_transcript_path


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
    def test_no_sessions_dir_returns_none(self, tmp_path):
        with patch("teleclaude.core.codex_transcript.Path.home", return_value=tmp_path):
            result = discover_codex_transcript_path("abc-123")
        assert result is None

    @pytest.mark.unit
    def test_finds_transcript_in_todays_dir(self, tmp_path):
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
    def test_returns_none_when_no_matching_file(self, tmp_path):
        sessions_dir = tmp_path / ".codex" / "sessions"
        sessions_dir.mkdir(parents=True)

        with patch("teleclaude.core.codex_transcript.Path.home", return_value=tmp_path):
            result = discover_codex_transcript_path("nonexistent-session")

        assert result is None
