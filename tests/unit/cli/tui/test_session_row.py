"""Reproduction tests for newline stripping in SessionRow._build_title_line."""

from __future__ import annotations

import pytest

from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui.widgets.session_row import SessionRow


def _make_session(title: str, subdir: str | None = None) -> SessionDTO:
    return SessionDTO(
        session_id="test-session-id",
        title=title,
        status="idle",
        subdir=subdir,
    )


def _make_row(title: str, subdir: str | None = None) -> SessionRow:
    return SessionRow(
        session=_make_session(title, subdir=subdir),
        display_index="1",
        depth=0,
    )


@pytest.mark.unit
def test_title_with_unix_newline_renders_first_line_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug reproduction: title containing \\n must not bleed into a second line."""
    row = _make_row("First line\nSecond line")
    monkeypatch.setattr(type(row), "_content_width", property(lambda _: 80))

    text = row._build_title_line()
    plain = text.plain

    assert "Second line" not in plain
    assert "First line" in plain
    assert "\n" not in plain


@pytest.mark.unit
def test_title_with_crlf_newline_renders_first_line_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: \\r\\n (Windows-style) must also be stripped."""
    row = _make_row("First line\r\nSecond line")
    monkeypatch.setattr(type(row), "_content_width", property(lambda _: 80))

    text = row._build_title_line()
    plain = text.plain

    assert "Second line" not in plain
    assert "First line" in plain
    assert "\n" not in plain
    assert "\r" not in plain


@pytest.mark.unit
def test_title_that_is_only_newline_renders_empty_first_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge case: title=\\n yields an empty first line (not '(untitled)')."""
    row = _make_row("\n")
    monkeypatch.setattr(type(row), "_content_width", property(lambda _: 80))

    text = row._build_title_line()
    plain = text.plain

    # splitlines()[0] on "\n" returns "" — document this behavior
    assert "\n" not in plain
    assert "(untitled)" not in plain
