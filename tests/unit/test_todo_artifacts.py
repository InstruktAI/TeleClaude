"""Tests for the lightweight todo_artifacts module."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.todo_artifacts import (
    artifact_display_filename,
    read_artifact_content,
    write_artifact_content,
)


def test_artifact_display_filename_returns_input() -> None:
    """The display filename helper must not invent extensions or transforms."""
    assert artifact_display_filename("requirements") == "requirements"
    assert artifact_display_filename("plan.md") == "plan.md"


def test_read_artifact_content_refuses_missing_db(tmp_path: Path) -> None:
    """Missing project todos.db raises rather than silently bootstrapping a new one."""
    with pytest.raises(FileNotFoundError, match="Todos DB not found"):
        read_artifact_content(tmp_path, "any-slug", "requirements")


def test_write_artifact_content_refuses_missing_db(tmp_path: Path) -> None:
    """Missing project todos.db must not be auto-created on write."""
    with pytest.raises(FileNotFoundError, match="Todos DB not found"):
        write_artifact_content(tmp_path, "any-slug", "requirements", "content")
