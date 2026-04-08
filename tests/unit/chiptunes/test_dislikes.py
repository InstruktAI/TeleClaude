"""Characterization tests for teleclaude.chiptunes.dislikes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import teleclaude.chiptunes.dislikes as dislikes


class _FrozenDateTime:
    @classmethod
    def now(cls, tz: object) -> datetime:
        assert tz is UTC
        return datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.mark.unit
class TestDislikes:
    def test_load_dislikes_missing_file_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(dislikes, "DISLIKES_PATH", tmp_path / "dislikes.json")
        assert dislikes.load_dislikes() == []

    def test_load_dislikes_invalid_content_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "dislikes.json"
        path.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(dislikes, "DISLIKES_PATH", path)

        assert dislikes.load_dislikes() == []

        path.write_text(json.dumps({"track_name": "Song"}), encoding="utf-8")
        assert dislikes.load_dislikes() == []

    def test_save_dislike_appends_timestamped_entry_and_deduplicates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "nested" / "dislikes.json"
        monkeypatch.setattr(dislikes, "DISLIKES_PATH", path)
        monkeypatch.setattr(dislikes, "datetime", _FrozenDateTime)

        dislikes.save_dislike("Annoying Song", "/music/annoying.sid")
        dislikes.save_dislike("Duplicate", "/music/annoying.sid")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == [
            {
                "track_name": "Annoying Song",
                "sid_path": "/music/annoying.sid",
                "saved_at": "2024-01-02T03:04:05+00:00",
            }
        ]

    def test_remove_dislike_rewrites_file_and_reports_if_anything_changed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "dislikes.json"
        path.write_text(
            json.dumps(
                [
                    {"track_name": "A", "sid_path": "/music/a.sid"},
                    {"track_name": "B", "sid_path": "/music/b.sid"},
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(dislikes, "DISLIKES_PATH", path)

        assert dislikes.remove_dislike("/music/a.sid") is True
        assert dislikes.remove_dislike("/music/missing.sid") is False
        assert json.loads(path.read_text(encoding="utf-8")) == [{"track_name": "B", "sid_path": "/music/b.sid"}]

    def test_is_disliked_checks_sid_path_membership(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        path = tmp_path / "dislikes.json"
        path.write_text(json.dumps([{"track_name": "Bad", "sid_path": "/music/bad.sid"}]), encoding="utf-8")
        monkeypatch.setattr(dislikes, "DISLIKES_PATH", path)

        assert dislikes.is_disliked("/music/bad.sid") is True
        assert dislikes.is_disliked("/music/other.sid") is False

    def test_disliked_paths_returns_set_of_sid_paths(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        path = tmp_path / "dislikes.json"
        path.write_text(
            json.dumps(
                [
                    {"track_name": "A", "sid_path": "/music/a.sid"},
                    {"track_name": "B", "sid_path": "/music/b.sid"},
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(dislikes, "DISLIKES_PATH", path)

        assert dislikes.disliked_paths() == {"/music/a.sid", "/music/b.sid"}

    def test_disliked_paths_empty_when_no_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(dislikes, "DISLIKES_PATH", tmp_path / "dislikes.json")
        assert dislikes.disliked_paths() == set()
