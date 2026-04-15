# pylint: disable=import-outside-toplevel
"""Tests for teleclaude.quality.scope — shared scope utilities."""

from __future__ import annotations

from pathlib import Path


class TestResolveProjectRoot:  # pylint: disable=too-few-public-methods
    """resolve_project_root walks up to find teleclaude.yml."""

    def test_finds_root_with_teleclaude_yml(self, tmp_path: Path) -> None:
        """Returns the directory containing teleclaude.yml."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)

        from teleclaude.quality.scope import resolve_project_root

        assert resolve_project_root(sub) == tmp_path


class TestValidateScopedPaths:
    """validate_scoped_paths filters out dangerous paths."""

    def test_filters_traversal_paths(self, tmp_path: Path) -> None:
        """Paths containing '..' are rejected."""
        from teleclaude.quality.scope import validate_scoped_paths

        result = validate_scoped_paths(["../etc/passwd", "ok.py"], tmp_path)
        assert result == ["ok.py"]

    def test_filters_absolute_paths_outside_root(self, tmp_path: Path) -> None:
        """Absolute paths outside project root are rejected."""
        from teleclaude.quality.scope import validate_scoped_paths

        result = validate_scoped_paths(["/etc/passwd", "ok.py"], tmp_path)
        assert result == ["ok.py"]
