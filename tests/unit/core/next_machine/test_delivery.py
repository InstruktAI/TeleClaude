"""Tests for physical delivery cleanup and binary artifact archival."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.delivery import _archive_binary_artifacts


class TestArchiveBinaryArtifacts:
    """Tests for _archive_binary_artifacts — moves art/html/input dirs to permanent storage."""

    @pytest.fixture()
    def storage_root(self, tmp_path: Path) -> Path:
        return tmp_path / "storage"

    @pytest.fixture(autouse=True)
    def _patch_storage_and_date(self, storage_root: Path) -> Iterator[None]:
        fake_date = type(
            "FakeDate", (), {"today": staticmethod(lambda: type("D", (), {"isoformat": lambda self: "2026-01-15"})())}
        )
        with (
            patch("teleclaude.core.next_machine.delivery._STORAGE_ROOT", storage_root),
            patch("teleclaude.core.next_machine.delivery.date", fake_date),
        ):
            yield

    @staticmethod
    def _make_worktree(tmp_path: Path, slug: str, dirs: dict[str, list[str]]) -> Path:
        """Create a fake worktree with the given artifact dirs and files."""
        worktree = tmp_path / "trees" / slug
        for dirname, files in dirs.items():
            artifact_dir = worktree / "todos" / slug / dirname
            artifact_dir.mkdir(parents=True, exist_ok=True)
            for fname in files:
                (artifact_dir / fname).write_bytes(b"binary data")
        return worktree

    @pytest.mark.unit
    def test_archive_moves_art_dir_to_storage(self, tmp_path: Path, storage_root: Path) -> None:
        worktree = self._make_worktree(tmp_path, "my-slug", {"art": ["mood.png", "logo.svg"]})

        _archive_binary_artifacts(worktree, "my-slug")

        art_dest = storage_root / "2026-01-15" / "my-slug" / "art"
        assert art_dest.is_dir()
        assert {f.name for f in art_dest.iterdir()} == {"mood.png", "logo.svg"}
        assert not (worktree / "todos" / "my-slug" / "art").exists()

    @pytest.mark.unit
    def test_archive_moves_html_dir_to_storage(self, tmp_path: Path, storage_root: Path) -> None:
        worktree = self._make_worktree(tmp_path, "my-slug", {"html": ["index.html"]})

        _archive_binary_artifacts(worktree, "my-slug")

        html_dest = storage_root / "2026-01-15" / "my-slug" / "html"
        assert html_dest.is_dir()
        assert (html_dest / "index.html").exists()

    @pytest.mark.unit
    def test_archive_skips_missing_worktree(self, tmp_path: Path, storage_root: Path) -> None:
        nonexistent = tmp_path / "trees" / "gone"

        _archive_binary_artifacts(nonexistent, "gone")

        assert not storage_root.exists()

    @pytest.mark.unit
    def test_archive_skips_empty_dirs(self, tmp_path: Path, storage_root: Path) -> None:
        worktree = tmp_path / "trees" / "my-slug"
        (worktree / "todos" / "my-slug" / "art").mkdir(parents=True)

        _archive_binary_artifacts(worktree, "my-slug")

        assert not storage_root.exists()

    @pytest.mark.unit
    def test_archive_noop_when_no_binary_dirs(self, tmp_path: Path, storage_root: Path) -> None:
        worktree = tmp_path / "trees" / "my-slug"
        (worktree / "todos" / "my-slug" / "src").mkdir(parents=True)
        (worktree / "todos" / "my-slug" / "src" / "main.py").write_text("code")

        _archive_binary_artifacts(worktree, "my-slug")

        assert not storage_root.exists()
