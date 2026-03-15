"""Characterization tests for teleclaude.cli.tui.widgets.project_header."""

from __future__ import annotations

import pytest

from teleclaude.cli.models import ProjectInfo
from teleclaude.cli.tui.widgets.project_header import ProjectHeader


def _make_project(*, name: str = "my-project", path: str = "/tmp/my-project") -> ProjectInfo:
    return ProjectInfo(computer="local", name=name, path=path)


@pytest.mark.unit
def test_project_header_is_importable() -> None:
    assert ProjectHeader is not None


@pytest.mark.unit
def test_project_header_stores_project() -> None:
    project = _make_project()
    header = ProjectHeader(project=project)
    assert header.project is project


@pytest.mark.unit
def test_project_header_default_session_count_is_zero() -> None:
    project = _make_project()
    header = ProjectHeader(project=project)
    assert header.session_count == 0


@pytest.mark.unit
def test_project_header_accepts_session_count() -> None:
    project = _make_project()
    header = ProjectHeader(project=project, session_count=3)
    assert header.session_count == 3


@pytest.mark.unit
def test_project_header_connector_col_class_constant_is_two() -> None:
    assert ProjectHeader.CONNECTOR_COL == 2


@pytest.mark.unit
def test_project_header_pressed_message_is_defined() -> None:
    assert ProjectHeader.Pressed is not None
