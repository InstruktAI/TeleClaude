"""Functional tests for session-row out-line retention and the disk-write guard."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest
from textual.app import App, ComposeResult

from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.views.sessions_highlights import PREVIEW_HIGHLIGHT_DURATION
from teleclaude.cli.tui.widgets.session_row import SessionRow

pytestmark = pytest.mark.functional

SID = "s1"
OTHER_SID = "s2"


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
