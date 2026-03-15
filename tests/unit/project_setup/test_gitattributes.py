"""Characterization tests for teleclaude.project_setup.gitattributes."""

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.project_setup.gitattributes as gitattributes


def test_update_gitattributes_appends_missing_patterns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gitattributes_path = tmp_path / ".gitattributes"
    gitattributes_path.write_text("* text=auto", encoding="utf-8")

    gitattributes.update_gitattributes(tmp_path)

    content = gitattributes_path.read_text(encoding="utf-8")
    assert "* text=auto\n" in content
    for pattern in gitattributes.FILTER_PATTERNS:
        assert pattern in content
    assert ".gitattributes updated" in capsys.readouterr().out


def test_update_gitattributes_is_idempotent(tmp_path: Path) -> None:
    gitattributes.update_gitattributes(tmp_path)
    gitattributes.update_gitattributes(tmp_path)

    lines = (tmp_path / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for pattern in gitattributes.FILTER_PATTERNS:
        assert lines.count(pattern) == 1
