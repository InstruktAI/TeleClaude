"""Functional tests for pinned computer ordering and partial-state repaint.

Drives the real views (and the websocket project-initial handler) through their
update paths and asserts the rendered computer-header order: local first, then
case-insensitive alphabetical, held stable regardless of arrival order. Also
pins that an authoritative computer/project set repaints the views after a
partial-state render, and that a project-initial event merges by each incoming
project's owning computer rather than dropping other computers.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from teleclaude.api_models import (
    ComputerDTO,
    ProjectsInitialDataDTO,
    ProjectsInitialEventDTO,
    ProjectWithTodosDTO,
    SessionDTO,
)
from teleclaude.cli.tui.app_ws import TelecAppWsMixin
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.config import config

pytestmark = pytest.mark.functional

_LOCAL = config.computer.name


def _computer(name: str, *, is_local: bool = False) -> ComputerDTO:
    return ComputerDTO(name=name, status="online", user=None, host=None, is_local=is_local)


def _project(computer: str, path: str) -> ProjectWithTodosDTO:
    return ProjectWithTodosDTO(computer=computer, name="", path=path, description=None, todos=[])


def _session(session_id: str, *, computer: str) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="active",
        created_at="2026-06-18T01:00:00",
        project_path="/repo",
        computer=computer,
    )


def _header_names(view: PreparationView | SessionsView) -> list[str]:
    return [w.data.computer.name for w in view._nav_items if isinstance(w, ComputerHeader)]


class _PrepApp(App[None]):
    def compose(self) -> ComposeResult:
        yield PreparationView(id="preparation-view")


class _SessionsApp(App[None]):
    def compose(self) -> ComposeResult:
        yield SessionsView(id="sessions-view")


class _WsApp(TelecAppWsMixin, App[None]):
    def compose(self) -> ComposeResult:
        yield SessionsView(id="sessions-view")
        yield PreparationView(id="preparation-view")


@pytest.mark.asyncio
async def test_preparation_pins_local_first_then_alphabetical() -> None:
    app = _PrepApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(PreparationView)
        # Arrival order is remote-first and unsorted; the render order must not be.
        view.update_data(
            [
                _project("z-remote", "/z"),
                _project("A-remote", "/a"),
                _project(_LOCAL, "/local"),
            ]
        )
        await pilot.pause()

        assert _header_names(view) == [_LOCAL, "A-remote", "z-remote"]


@pytest.mark.asyncio
async def test_sessions_repaints_when_computer_set_changes_with_same_sessions() -> None:
    app = _SessionsApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(SessionsView)
        session = _session("s1", computer=_LOCAL)
        view.update_data(computers=[_computer(_LOCAL, is_local=True)], projects=[], sessions=[session])
        await pilot.pause()
        assert _header_names(view) == [_LOCAL]

        # Same session set, but an authoritative computer arrives. The guard must
        # repaint on the computer-set change so the new computer renders.
        view.update_data(
            computers=[_computer(_LOCAL, is_local=True), _computer("new-remote")],
            projects=[],
            sessions=[session],
        )
        await pilot.pause()
        assert _header_names(view) == [_LOCAL, "new-remote"]


def _projects_event(computer: str, projects: list[ProjectWithTodosDTO]) -> ProjectsInitialEventDTO:
    return ProjectsInitialEventDTO(
        event="projects_initial",
        data=ProjectsInitialDataDTO(projects=list(projects), computer=computer),
    )


@pytest.mark.asyncio
async def test_project_initial_events_merge_by_incoming_computer() -> None:
    app = _WsApp()
    async with app.run_test(size=(100, 40)) as pilot:
        prep_view = app.query_one(PreparationView)

        # Two per-remote events arrive; the second must not drop the first.
        app._handle_initial_data_event(_projects_event("z-remote", [_project("z-remote", "/z")]))
        await pilot.pause()
        app._handle_initial_data_event(_projects_event("A-remote", [_project("A-remote", "/a")]))
        await pilot.pause()
        assert set(_header_names(prep_view)) == {"z-remote", "A-remote"}

        # A local full-set event (label "local", payload carrying the local
        # computer) merges in without dropping the retained remotes.
        app._handle_initial_data_event(_projects_event("local", [_project(_LOCAL, "/local")]))
        await pilot.pause()

        names = _header_names(prep_view)
        assert names == [_LOCAL, "A-remote", "z-remote"]
        assert len(names) == len(set(names))


@pytest.mark.asyncio
async def test_empty_scoped_snapshot_clears_that_computer() -> None:
    app = _WsApp()
    async with app.run_test(size=(100, 40)) as pilot:
        prep_view = app.query_one(PreparationView)

        app._handle_initial_data_event(_projects_event("Raspi", [_project("Raspi", "/r")]))
        await pilot.pause()
        assert _header_names(prep_view) == ["Raspi"]

        # An authoritative empty snapshot for the same remote must clear it —
        # the replacement identity comes from the event label, not the (empty)
        # payload.
        app._handle_initial_data_event(_projects_event("Raspi", []))
        await pilot.pause()
        assert _header_names(prep_view) == []
