# guard: no-companion
"""Characterization tests for SessionRow rendering and summary hierarchy."""

from __future__ import annotations

import pytest

from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui.utils.formatters import format_time
from teleclaude.cli.tui.widgets.session_row import SessionRow


def _make_session(title: str, subdir: str | None = None, **overrides: object) -> SessionDTO:
    return SessionDTO(
        session_id="test-session-id",
        title=title,
        status="idle",
        subdir=subdir,
        last_activity="2026-03-31T17:17:37Z",
        last_input="Run the planner",
        last_input_at="2026-03-31T17:13:17Z",
        last_output_summary="Completed the requested work",
        last_output_summary_at="2026-03-31T17:17:37Z",
        native_session_id="native-session-id",
        **overrides,
    )


def _make_row(title: str, subdir: str | None = None, **overrides: object) -> SessionRow:
    return SessionRow(
        session=_make_session(title, subdir=subdir, **overrides),
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


@pytest.mark.unit
def test_collapsed_render_shows_summary_lines_but_not_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _make_row("Planner Session", human_name="Maurice Faber", human_role="admin")
    monkeypatch.setattr(type(row), "_content_width", property(lambda _: 120))
    monkeypatch.setattr(
        "teleclaude.cli.tui.widgets.session_row.read_current_session_email", lambda: "other@instrukt.ai"
    )

    text = row.render().plain

    assert "admin: Maurice Faber" in text
    assert "in: Run the planner" in text
    assert "out: Completed the requested work" in text
    assert "test-session-id / native-session-id" not in text


@pytest.mark.unit
def test_expanded_render_shows_technical_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _make_row("Planner Session", created_at="2026-03-31T16:00:00Z")
    row.collapsed = False
    monkeypatch.setattr(type(row), "_content_width", property(lambda _: 120))

    text = row.render().plain

    assert f"[{format_time('2026-03-31T16:00:00Z')}]" in text
    assert "test-session-id / native-session-id" in text


@pytest.mark.unit
def test_expanded_render_places_technical_ids_before_summary_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _make_row("Planner Session", created_at="2026-03-31T16:00:00Z")
    row.collapsed = False
    monkeypatch.setattr(type(row), "_content_width", property(lambda _: 120))

    text = row.render().plain

    assert text.index("test-session-id / native-session-id") < text.index("in: Run the planner")


@pytest.mark.unit
def test_unresolved_session_does_not_render_system_role_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _make_row("Planner Session", human_role="member", system_role="worker", job="next-build")
    monkeypatch.setattr(type(row), "_content_width", property(lambda _: 120))

    text = row.render().plain

    assert "worker: next-build" not in text


@pytest.mark.unit
def test_current_viewer_identity_line_is_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _make_row(
        "Planner Session",
        human_name="Maurice Faber",
        human_role="admin",
        human_email="maurice@instrukt.ai",
    )
    monkeypatch.setattr(type(row), "_content_width", property(lambda _: 120))
    monkeypatch.setattr(
        "teleclaude.cli.tui.widgets.session_row.read_current_session_email",
        lambda: "maurice@instrukt.ai",
    )

    text = row.render().plain

    assert "admin: Maurice Faber" not in text
