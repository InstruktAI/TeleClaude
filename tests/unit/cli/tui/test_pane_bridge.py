from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import TypedDict

import pytest

from teleclaude.api_models import ComputerDTO, SessionDTO
from teleclaude.cli.tui.messages import DataRefreshed, PreviewChanged
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge


class _CatalogCall(TypedDict):
    catalog: tuple[str, ...]


class _ApplyCall(TypedDict):
    active_session_id: str | None
    sticky_session_ids: list[str]
    get_computer_info: object
    active_doc_preview: object | None
    focus: bool


class _SeedReloadCall(TypedDict):
    active_session_id: str | None
    sticky_session_ids: list[str]
    get_computer_info: object


class _WriterStub:
    def __init__(self) -> None:
        self.scheduled: list[Callable[[], None]] = []
        self.stopped = False

    def schedule(self, fn: Callable[[], None]) -> None:
        self.scheduled.append(fn)

    def stop(self) -> None:
        self.stopped = True


def _make_session(
    session_id: str,
    *,
    title: str = "title",
    status: str = "idle",
    computer: str = "c1",
) -> SessionDTO:
    return SessionDTO(session_id=session_id, title=title, status=status, computer=computer)


def _session_snapshot(sessions: list[SessionDTO]) -> tuple[tuple[str, str, str, str], ...]:
    return tuple((session.session_id, session.title, session.status, session.computer) for session in sessions)


@pytest.mark.unit
def test_set_preview_schedules_layout_with_snapshot_state() -> None:
    pane_manager = SimpleNamespace(
        update_session_catalog=lambda sessions: None,
        apply_layout=lambda **kwargs: None,
    )
    writer = _WriterStub()
    bridge = object.__new__(PaneManagerBridge)
    bridge.pane_manager = pane_manager
    bridge._writer = writer
    bridge._sessions = [SessionDTO(session_id="session-1", title="title", status="idle", computer="c1")]
    bridge._preview_session_id = None
    bridge._sticky_session_ids = ["sticky-1"]
    bridge._active_doc_preview = None
    bridge._get_computer_info = lambda name: None
    calls: list[_CatalogCall | _ApplyCall] = []
    bridge.pane_manager = SimpleNamespace(
        update_session_catalog=lambda sessions: calls.append(
            {"catalog": tuple(session.session_id for session in sessions)}
        ),
        apply_layout=lambda **kwargs: calls.append(kwargs),
    )

    bridge.on_preview_changed(PreviewChanged("session-1", request_focus=True))
    scheduled = writer.scheduled[0]
    scheduled()

    assert bridge._preview_session_id == "session-1"
    assert calls == [
        {"catalog": ("session-1",)},
        {
            "active_session_id": "session-1",
            "sticky_session_ids": ["sticky-1"],
            "get_computer_info": bridge._get_computer_info,
            "active_doc_preview": None,
            "focus": True,
        },
    ]


@pytest.mark.unit
def test_update_single_session_replaces_existing_session_and_updates_catalog() -> None:
    catalog_calls: list[tuple[tuple[str, str, str, str], ...]] = []
    existing = _make_session("session-1", title="old")
    untouched = _make_session("session-2", title="keep")
    replacement = _make_session("session-1", title="new", status="running")
    bridge = object.__new__(PaneManagerBridge)
    bridge._sessions = [existing, untouched]
    bridge.pane_manager = SimpleNamespace(
        update_session_catalog=lambda sessions: catalog_calls.append(_session_snapshot(sessions))
    )

    bridge.update_single_session(replacement)

    assert bridge._sessions == [replacement, untouched]
    assert catalog_calls == [
        (
            ("session-1", "new", "running", "c1"),
            ("session-2", "keep", "idle", "c1"),
        )
    ]


@pytest.mark.unit
def test_update_single_session_appends_new_session_and_updates_catalog() -> None:
    catalog_calls: list[tuple[tuple[str, str, str, str], ...]] = []
    existing = _make_session("session-1", title="keep")
    new_session = _make_session("session-2", title="new", status="running")
    bridge = object.__new__(PaneManagerBridge)
    bridge._sessions = [existing]
    bridge.pane_manager = SimpleNamespace(
        update_session_catalog=lambda sessions: catalog_calls.append(_session_snapshot(sessions))
    )

    bridge.update_single_session(new_session)

    assert bridge._sessions == [existing, new_session]
    assert catalog_calls == [
        (
            ("session-1", "keep", "idle", "c1"),
            ("session-2", "new", "running", "c1"),
        )
    ]


@pytest.mark.unit
def test_remove_session_filters_existing_session_and_updates_catalog() -> None:
    catalog_calls: list[tuple[tuple[str, str, str, str], ...]] = []
    keep = _make_session("session-1", title="keep")
    remove = _make_session("session-2", title="drop")
    bridge = object.__new__(PaneManagerBridge)
    bridge._sessions = [keep, remove]
    bridge.pane_manager = SimpleNamespace(
        update_session_catalog=lambda sessions: catalog_calls.append(_session_snapshot(sessions))
    )

    bridge.remove_session("session-2")

    assert bridge._sessions == [keep]
    assert catalog_calls == [(("session-1", "keep", "idle", "c1"),)]


@pytest.mark.unit
def test_remove_session_is_idempotent_for_missing_session_id() -> None:
    catalog_calls: list[tuple[tuple[str, str, str, str], ...]] = []
    existing = _make_session("session-1", title="keep")
    bridge = object.__new__(PaneManagerBridge)
    bridge._sessions = [existing]
    bridge.pane_manager = SimpleNamespace(
        update_session_catalog=lambda sessions: catalog_calls.append(_session_snapshot(sessions))
    )

    bridge.remove_session("missing")

    assert bridge._sessions == [existing]
    assert catalog_calls == [(("session-1", "keep", "idle", "c1"),)]


@pytest.mark.unit
def test_on_data_refreshed_updates_cached_state_and_seeds_reload_when_needed() -> None:
    seed_calls: list[_CatalogCall | _SeedReloadCall] = []
    pane_manager = SimpleNamespace(
        update_session_catalog=lambda sessions: seed_calls.append(
            {"catalog": tuple(session.session_id for session in sessions)}
        ),
        seed_for_reload=lambda **kwargs: seed_calls.append(kwargs),
        _reload_session_panes={"tc_demo": "%2"},
        _reload_command_panes=[],
    )
    bridge = object.__new__(PaneManagerBridge)
    bridge.pane_manager = pane_manager
    bridge._writer = _WriterStub()
    bridge._preview_session_id = "session-1"
    bridge._sticky_session_ids = ["sticky-1"]
    bridge._get_computer_info = lambda name: None
    computers = [ComputerDTO(name="c1", status="online", user="alice", host="host", is_local=True)]
    sessions = [SessionDTO(session_id="session-1", title="title", status="idle", computer="c1")]

    bridge.on_data_refreshed(DataRefreshed(computers, [], [], sessions, {}, [], True))

    assert bridge._computers == {"c1": computers[0]}
    assert bridge._sessions == sessions
    assert seed_calls == [
        {"catalog": ("session-1",)},
        {
            "active_session_id": "session-1",
            "sticky_session_ids": ["sticky-1"],
            "get_computer_info": bridge._get_computer_info,
        },
    ]


@pytest.mark.unit
def test_cleanup_stops_writer_and_delegates_to_pane_manager() -> None:
    writer = _WriterStub()
    pane_manager = SimpleNamespace(cleanup=lambda: setattr(pane_manager, "cleaned", True), cleaned=False)
    bridge = object.__new__(PaneManagerBridge)
    bridge._writer = writer
    bridge.pane_manager = pane_manager

    bridge.cleanup()

    assert writer.stopped is True
    assert pane_manager.cleaned is True
