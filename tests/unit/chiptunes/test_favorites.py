"""Characterization tests for teleclaude.chiptunes.favorites."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import teleclaude.chiptunes.favorites as favorites


class _FrozenDateTime:
    @classmethod
    def now(cls, tz: object) -> datetime:
        assert tz is UTC
        return datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.mark.unit
class TestFavorites:
    def test_load_favorites_missing_file_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(favorites, "FAVORITES_PATH", tmp_path / "favorites.json")
        assert favorites.load_favorites() == []

    def test_load_favorites_invalid_content_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "favorites.json"
        path.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(favorites, "FAVORITES_PATH", path)

        assert favorites.load_favorites() == []

        path.write_text(json.dumps({"track_name": "Song"}), encoding="utf-8")
        assert favorites.load_favorites() == []

    def test_save_favorite_appends_timestamped_entry_and_deduplicates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "nested" / "favorites.json"
        monkeypatch.setattr(favorites, "FAVORITES_PATH", path)
        monkeypatch.setattr(favorites, "datetime", _FrozenDateTime)

        favorites.save_favorite("Cybernoid", "/music/cybernoid.sid")
        favorites.save_favorite("Duplicate", "/music/cybernoid.sid")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == [
            {
                "track_name": "Cybernoid",
                "sid_path": "/music/cybernoid.sid",
                "saved_at": "2024-01-02T03:04:05+00:00",
            }
        ]

    def test_remove_favorite_rewrites_file_and_reports_if_anything_changed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "favorites.json"
        path.write_text(
            json.dumps(
                [
                    {"track_name": "A", "sid_path": "/music/a.sid"},
                    {"track_name": "B", "sid_path": "/music/b.sid"},
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(favorites, "FAVORITES_PATH", path)

        assert favorites.remove_favorite("/music/a.sid") is True
        assert favorites.remove_favorite("/music/missing.sid") is False
        assert json.loads(path.read_text(encoding="utf-8")) == [{"track_name": "B", "sid_path": "/music/b.sid"}]

    def test_is_favorited_checks_sid_path_membership(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        path = tmp_path / "favorites.json"
        path.write_text(json.dumps([{"track_name": "Monty", "sid_path": "/music/monty.sid"}]), encoding="utf-8")
        monkeypatch.setattr(favorites, "FAVORITES_PATH", path)

        assert favorites.is_favorited("/music/monty.sid") is True
        assert favorites.is_favorited("/music/other.sid") is False
