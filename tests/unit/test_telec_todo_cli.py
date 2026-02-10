"""Tests for telec todo CLI command."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pytest

from teleclaude.cli import telec


class TodoCreateCall(TypedDict, total=False):
    project_root: Path
    slug: str
    after: list[str] | None


def test_handle_todo_create_invokes_scaffold(monkeypatch: pytest.MonkeyPatch) -> None:
    called: TodoCreateCall = {}

    def fake_create(project_root: Path, slug: str, *, after: list[str] | None = None) -> Path:
        called["project_root"] = project_root
        called["slug"] = slug
        called["after"] = after
        return project_root / "todos" / slug

    monkeypatch.setattr(telec, "create_todo_skeleton", fake_create)

    telec._handle_todo(["create", "my-slug", "--after", "a,b"])

    assert called["slug"] == "my-slug"
    assert called["after"] == ["a", "b"]


def test_handle_todo_create_requires_slug(capsys: pytest.CaptureFixture[str]) -> None:
    telec._handle_todo(["create"])
    out = capsys.readouterr().out
    assert "telec todo create <slug>" in out
