"""Characterization tests for teleclaude.resource_validation package helpers."""
# guard: no-companion

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import teleclaude.resource_validation as resource_validation

pytestmark = pytest.mark.unit


def test_validate_all_todos_enumerates_active_slugs_from_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[str] = []

    def _fake_validate_todo(slug: str, root: Path) -> list[str]:
        assert root == tmp_path
        seen.append(slug)
        return []

    monkeypatch.setattr(resource_validation, "validate_todo", _fake_validate_todo)

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE roadmap (id TEXT, slug TEXT, position INTEGER, status TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO roadmap VALUES ('1', 'active-slug', 1, 'active', '', '')",
    )
    conn.execute(
        "INSERT INTO roadmap VALUES ('2', 'frozen-slug', 2, 'icebox', '', '')",
    )
    conn.commit()

    mock_db = MagicMock()
    mock_db._sync_conn.return_value = conn

    with patch("teleclaude.core.next_machine.state_io._get_todos_db_sync", return_value=mock_db):
        errors = resource_validation.validate_all_todos(tmp_path)

    assert not errors
    assert seen == ["active-slug"]
