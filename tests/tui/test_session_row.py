"""Functional tests for session-row out-line retention and the disk-write guard."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest
from textual.app import App, ComposeResult

import teleclaude.cli.tui.widgets.chip as chip_mod
from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui.theme import get_selection_fg_hex
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.views.sessions_highlights import PREVIEW_HIGHLIGHT_DURATION
from teleclaude.cli.tui.widgets.session_row import SessionRow
from teleclaude.core.models import SessionSnapshot

pytestmark = pytest.mark.functional

SID = "s1"
OTHER_SID = "s2"

XNAV_SPEC = "project/spec/feature/tui/todo-session-cross-navigation"

ALICE = {"name": "Alice Smith", "email": "alice@example.com", "slug": "alice-smith"}
BOB = {"name": "Bob Jones", "email": "bob@example.com", "slug": "bob-jones"}


def _span_over(rendered: object, text: str) -> object | None:
    pos = rendered.plain.index(text)
    for span in rendered._spans:
        if span.start == pos and span.end == pos + len(text):
            return span
    return None


@pytest.fixture
def utc_timezone() -> Iterator[None]:
    """Pin the process timezone to UTC for the test, then restore it.

    ``tzset()`` mutates process-global state, so the prior ``TZ`` must be
    restored in teardown or later tests in the same worker inherit UTC.
    """
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def _session(session_id: str, *, last_output_summary: str | None = None) -> SessionDTO:
    # last_activity left None so format_time yields "" — keeps snapshots
    # timezone-independent (the retained text, not the timestamp, is the contract).
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="idle",
        tmux_session_name=f"tmux-{session_id}",
        active_agent="claude",
        computer="local",
        project_path="/proj",
        last_output_summary=last_output_summary,
    )


class _SessionsTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield SessionsView()


def _only_row(view: SessionsView, session_id: str) -> SessionRow:
    rows = [w for w in view._nav_items if isinstance(w, SessionRow) and w.session_id == session_id]
    assert len(rows) == 1
    return rows[0]


@pytest.mark.asyncio
async def test_out_line_retained_across_activity_clear_and_rebuild(snapshot: object) -> None:
    app = _SessionsTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(SessionsView)
        view.update_data(computers=[], projects=[], sessions=[_session(SID)])
        await pilot.pause()

        view.update_activity(SID, "tool_use", "Read: foo.py")
        await pilot.pause()
        view.update_activity(SID, "user_prompt_submit")
        await pilot.pause()
        after_clear = _only_row(view, SID).render().plain

        # A second session appearing forces old_ids != new_ids → full rebuild.
        view.update_data(computers=[], projects=[], sessions=[_session(SID), _session(OTHER_SID)])
        await pilot.pause()
        after_rebuild = _only_row(view, SID).render().plain

    assert {"after_clear": after_clear, "after_rebuild": after_rebuild} == snapshot


@pytest.mark.asyncio
async def test_ephemeral_out_values_never_reach_disk(snapshot: object) -> None:
    app = _SessionsTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(SessionsView)
        view.update_data(computers=[], projects=[], sessions=[_session(SID)])
        await pilot.pause()

        view.update_activity(SID, "thinking", "pondering")
        view.update_activity(SID, "tool_use", "Read: foo.py")
        await pilot.pause()

        persisted = view.get_persisted_state()["last_output_summary"]
        assert isinstance(persisted, dict)
        # Live tool_use/thinking are retained in memory only — never serialized.
        assert SID not in persisted

        view.update_activity(SID, "agent_stop", "done summary")
        await pilot.pause()

        entry = view.get_persisted_state()["last_output_summary"]
        assert isinstance(entry, dict)
        agent_stop_entry = entry[SID]
        assert isinstance(agent_stop_entry, dict)
        # Normalize the monotonic timestamp to a sentinel so the snapshot pins
        # the durable text contract without a flaky time value.
        normalized = {"text": agent_stop_entry["text"], "ts": "<monotonic>"}

    assert normalized == snapshot


@pytest.mark.asyncio
async def test_out_line_retention_does_not_touch_highlight() -> None:
    assert PREVIEW_HIGHLIGHT_DURATION == 3.0
    app = _SessionsTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(SessionsView)
        view.update_data(computers=[], projects=[], sessions=[_session(SID)])
        await pilot.pause()
        row = _only_row(view, SID)
        baseline_highlight = row.highlight_type

        view.update_activity(SID, "tool_use", "Read: foo.py")
        await pilot.pause()

        # Retaining out-line text is independent of the highlight surface:
        # update_activity must not set or clear highlight_type on its own.
        assert row.highlight_type == baseline_highlight


@pytest.mark.asyncio
async def test_new_session_collapsed_by_default() -> None:
    app = _SessionsTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(SessionsView)
        view.update_data(computers=[], projects=[], sessions=[_session(SID)])
        await pilot.pause()

        # A session that appears in the tree renders collapsed by default.
        assert _only_row(view, SID).collapsed is True


@pytest.mark.asyncio
async def test_user_expanded_session_survives_rebuild() -> None:
    app = _SessionsTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(SessionsView)
        view.update_data(computers=[], projects=[], sessions=[_session(SID)])
        await pilot.pause()

        # Drive expansion through the real key binding: move the cursor onto the
        # session row, then press → (action_expand). No private state is set up.
        view.focus()
        target_index = view._nav_items.index(_only_row(view, SID))
        for _ in range(target_index):
            await pilot.press("down")
        await pilot.press("right")
        await pilot.pause()
        assert _only_row(view, SID).collapsed is False

        # A second session forces a full tree rebuild; the user-expanded session
        # stays expanded across it.
        view.update_data(computers=[], projects=[], sessions=[_session(SID), _session(OTHER_SID)])
        await pilot.pause()
        assert _only_row(view, SID).collapsed is False


def _owned_session(*, title: str, working_slug: str | None, human_email: str | None) -> SessionDTO:
    return SessionDTO(
        session_id=SID,
        title=title,
        status="idle",
        tmux_session_name=f"tmux-{SID}",
        active_agent="claude",
        thinking_mode="med",
        computer="local",
        project_path="/proj",
        working_slug=working_slug,
        human_email=human_email,
    )


def _title_line(session: SessionDTO) -> object:
    return SessionRow(session, display_index="1")._build_title_line()


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-5")
def test_orchestrator_row_single_slug_span_no_quotes(wire_people, snapshot) -> None:
    wire_people([ALICE, BOB])
    line = _title_line(
        _owned_session(
            title="/next-work config-public-surface-contract",
            working_slug="config-public-surface-contract",
            human_email="alice@example.com",
        )
    )
    # One chip + command + single highlighted slug; slug stripped from the title
    # text, no surrounding quotes.
    assert _span_over(line, "config-public-surface-contract") is not None
    assert line.plain == snapshot


def test_working_slug_projects_through_snapshot_dto_seam(wire_people, snapshot) -> None:
    wire_people([ALICE, BOB])
    snap = SessionSnapshot(
        session_id=SID,
        last_input_origin=None,
        title="/next-work projected-slug",
        thinking_mode="med",
        active_agent="claude",
        status="idle",
        tmux_session_name=f"tmux-{SID}",
        working_slug="projected-slug",
        human_email="alice@example.com",
    )
    # Drive the real transport seam the TUI consumes: SessionSnapshot.to_dict →
    # SessionDTO.from_core. The slug span renders only if both carry working_slug.
    dto = SessionDTO.from_core(snap, computer="local")
    line = _title_line(dto)
    assert _span_over(line, "projected-slug") is not None
    assert line.plain == snapshot


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-6")
def test_worker_row_renders_identically_to_orchestrator(wire_people, snapshot) -> None:
    wire_people([ALICE, BOB])
    line = _title_line(
        _owned_session(
            title="/next-build config-public-surface-contract",
            working_slug="config-public-surface-contract",
            human_email="alice@example.com",
        )
    )
    # Same chip + command + single slug layout; slug appears once, no
    # double-space before the command tail (pinned by the snapshot).
    assert _span_over(line, "config-public-surface-contract") is not None
    assert line.plain == snapshot


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-7")
def test_session_without_slug_renders_no_slug_span(wire_people, snapshot) -> None:
    wire_people([ALICE, BOB])
    line = _title_line(_owned_session(title="ad hoc shell work", working_slug=None, human_email="alice@example.com"))
    # No working slug → no highlighted slug span; title renders without quotes.
    # The snapshot is the contract: it carries the exact unquoted line with no
    # trailing slug span.
    assert line.plain == snapshot


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-3")
def test_session_human_chip_after_agent_mode(wire_people, monkeypatch) -> None:
    background, text = "#223344", "#ccddee"
    wire_people(
        [ALICE, BOB],
        overlays={"alice-smith": f"color:\n  background:\n    dark: '{background}'\n  text:\n    dark: '{text}'\n"},
    )
    monkeypatch.setattr(chip_mod, "is_dark_mode", lambda: True)

    line = _title_line(_owned_session(title="/next-work x", working_slug="x", human_email="alice@example.com"))

    chip_span = _span_over(line, "AS")
    agent_span = _span_over(line, "claude/med")
    assert chip_span is not None and agent_span is not None
    # Chip sits after the agent/mode segment and resolves alice's colors.
    assert chip_span.start >= agent_span.end
    assert chip_span.style.bgcolor.name == background
    assert chip_span.style.color.name == text


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-17")
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-18")
def test_session_chip_weight_and_color_track_selection_and_filter(wire_people) -> None:
    # Weight encodes selection/preview alone; color encodes the rest. Resting:
    # normal weight. Filter-on (not highlighted): colors swap, still normal.
    # Selected/previewed: bold, snapped to the high-contrast pole; selection
    # dominates the filter.
    wire_people([ALICE, BOB])

    def chip(*, selected: bool = False, previewed: bool = False, filtered: bool = False) -> object | None:
        row = SessionRow(
            _owned_session(title="/next-work x", working_slug="x", human_email="alice@example.com"),
            display_index="1",
        )
        if filtered:
            row._active_human_filter = "alice@example.com"
        return _span_over(row._build_title_line(selected=selected, previewed=previewed), "AS")

    resting = chip()
    filtered = chip(filtered=True)
    selected = chip(selected=True)
    previewed = chip(previewed=True)
    both = chip(selected=True, filtered=True)
    assert all(s is not None for s in (resting, filtered, selected, previewed, both))
    pole = get_selection_fg_hex()
    # Weight: bold only when highlighted.
    assert not resting.style.bold
    assert not filtered.style.bold
    assert selected.style.bold is True
    assert previewed.style.bold is True
    # Resting is low-contrast (not the pole). Filter-on, selection, and preview all
    # take the selection text pole over the opposite-pole fill (neutral chip).
    assert resting.style.color.name != pole
    for active in (filtered, selected, previewed, both):
        assert active.style.color.name == pole
        assert active.style.bgcolor.name in {"#000000", "#ffffff"}
        assert active.style.bgcolor.name != pole


class _JumpApp(App[None]):
    def __init__(self, row: SessionRow) -> None:
        super().__init__()
        self._row = row
        self.jumped: list[str] = []

    def compose(self) -> ComposeResult:
        yield self._row

    def on_jump_to_todo(self, message: object) -> None:
        self.jumped.append(message.slug)


@pytest.mark.asyncio
async def test_session_slug_click_jumps_to_todo(wire_people) -> None:
    # Row-level proof that a slug click emits JumpToTodo. UC-XNAV-13 is bound by
    # the full-app integration test in test_todo_session_cross_navigation.
    slug = "my-work-slug"
    wire_people([ALICE, BOB])
    row = SessionRow(
        _owned_session(title=f"/next-work {slug}", working_slug=slug, human_email="alice@example.com"),
        display_index="1",
    )
    app = _JumpApp(row)
    async with app.run_test(size=(120, 12)) as pilot:
        row.render()
        assert row._slug_region is not None
        # Click the start of the recorded work-slug span on the title line.
        await pilot.click(row, offset=(1 + row._slug_region[0], 0))
        await pilot.pause()
        # Clicking the highlighted work-slug span jumps to the matching todo.
        assert app.jumped == [slug]


@pytest.mark.asyncio
async def test_select_session_lands_cursor_and_preview() -> None:
    # View-level proof of the select-and-preview mechanism. UC-XNAV-12 is bound
    # by the full-app integration test in test_todo_session_cross_navigation.
    app = _SessionsTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(SessionsView)
        view.update_data(computers=[], projects=[], sessions=[_session(SID), _session(OTHER_SID)])
        await pilot.pause()

        view.select_session(OTHER_SID)
        await pilot.pause()
        # The cross-view jump lands the cursor on the target session and previews it.
        assert _only_row(view, OTHER_SID).has_class("selected")
        assert view.preview_session_id == OTHER_SID


def test_single_user_suppresses_session_chip(wire_people) -> None:
    # Single-user mode suppresses the session owner chip (SC-6).
    wire_people([ALICE])
    row = SessionRow(
        _owned_session(title="/next-work x", working_slug="x", human_email="alice@example.com"),
        display_index="1",
    )
    row.render()
    assert row._chip_region is None


def test_session_chip_and_slug_spans_carry_no_padding(wire_people) -> None:
    wire_people([ALICE, BOB])
    line = _title_line(
        _owned_session(title="/next-work my-slug", working_slug="my-slug", human_email="alice@example.com")
    )
    chip_span = _span_over(line, "AS")
    slug_span = _span_over(line, "my-slug")
    # Styled regions span exactly their own glyphs; the separators sit outside.
    assert chip_span is not None and slug_span is not None
    assert line.plain[chip_span.start - 1].isspace()
    assert line.plain[slug_span.start - 1].isspace()


@pytest.mark.asyncio
async def test_expanded_and_collapsed_row_rendering(utc_timezone: None, snapshot: object) -> None:
    # utc_timezone pins TZ so the rendered timestamps are deterministic.
    app = _SessionsTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        view = app.query_one(SessionsView)
        sess = SessionDTO(
            session_id=SID,
            title=SID,
            status="idle",
            tmux_session_name=f"tmux-{SID}",
            active_agent="claude",
            computer="local",
            project_path="/proj",
            created_at="2026-06-19T10:00:00+00:00",
            last_activity="2026-06-19T10:05:00+00:00",
            last_output_summary="hello world",
            native_session_id="nat-1",
        )
        view.update_data(computers=[], projects=[], sessions=[sess])
        await pilot.pause()
        row = _only_row(view, SID)

        row.collapsed = True
        await pilot.pause()
        collapsed = row.render().plain

        row.collapsed = False
        await pilot.pause()
        expanded = row.render().plain

    # Collapsed: bare HH:MM:SS, no date. Expanded: id line + out line carry the
    # -DD/MM suffix, ids slash-joined with no spaces, no leading pad after │.
    assert {"collapsed": collapsed, "expanded": expanded} == snapshot
