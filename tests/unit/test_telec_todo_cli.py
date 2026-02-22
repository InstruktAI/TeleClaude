"""Tests for telec todo CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest
from typing_extensions import TypedDict

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


class TodoRemoveCall(TypedDict, total=False):
    project_root: Path
    slug: str


def test_handle_todo_remove_invokes_remove_todo(monkeypatch: pytest.MonkeyPatch) -> None:
    called: TodoRemoveCall = {}

    def fake_remove(project_root: Path, slug: str) -> None:
        called["project_root"] = project_root
        called["slug"] = slug

    monkeypatch.setattr(telec, "remove_todo", fake_remove)

    telec._handle_todo(["remove", "my-slug"])

    assert called["slug"] == "my-slug"


def test_handle_todo_remove_requires_slug(capsys: pytest.CaptureFixture[str]) -> None:
    telec._handle_todo(["remove"])
    out = capsys.readouterr().out
    assert "telec todo remove <slug>" in out
