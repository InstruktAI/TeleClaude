"""Tests for teleclaude.todo_scaffold.create_draft_skeleton content guard."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude.constants import RoadmapStatus
from teleclaude.todo_scaffold import create_draft_skeleton

_VALUE_ERROR = ValueError


class TestCreateDraftSkeletonContentGuard:
    @pytest.mark.unit
    def test_empty_content_raises_value_error(self) -> None:
        with pytest.raises(_VALUE_ERROR):
            create_draft_skeleton("root", "my-slug", content="")

    @pytest.mark.unit
    def test_none_content_raises_value_error(self) -> None:
        with pytest.raises(_VALUE_ERROR):
            create_draft_skeleton("root", "my-slug")

    @pytest.mark.unit
    def test_whitespace_only_content_raises_value_error(self) -> None:
        with pytest.raises(_VALUE_ERROR):
            create_draft_skeleton("root", "my-slug", content="   ")

    @pytest.mark.unit
    def test_create_draft_skeleton_writes_positionless_roadmap_row(self, tmp_path: Path) -> None:
        slug = "my-slug"

        create_draft_skeleton(str(tmp_path), slug, content="Substantive input")

        conn = sqlite3.connect(tmp_path / ".teleclaude" / "todos.db")
        try:
            row = conn.execute(  # guard: raw-sql
                "SELECT slug, status FROM roadmap WHERE slug = ?",
                (slug,),
            ).fetchone()
        finally:
            conn.close()

        assert row == (slug, RoadmapStatus.ACTIVE)
