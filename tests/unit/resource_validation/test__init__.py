"""Characterization tests for teleclaude.resource_validation package helpers."""
# guard: no-companion

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.resource_validation as resource_validation

pytestmark = pytest.mark.unit


def test_validate_all_todos_skips_icebox_subfolder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    todos_root = tmp_path / "todos"
    (todos_root / "_icebox" / "frozen").mkdir(parents=True)
    (todos_root / "active").mkdir(parents=True)

    seen: list[str] = []

    def _fake_validate_todo(slug: str, root: Path) -> list[str]:
        assert root == tmp_path
        seen.append(slug)
        return []

    monkeypatch.setattr(resource_validation, "validate_todo", _fake_validate_todo)

    errors = resource_validation.validate_all_todos(tmp_path)

    assert errors == []
    assert seen == ["active"]
