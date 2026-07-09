"""Functional tests for voluntary todo claim release."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from syrupy.assertion import SnapshotAssertion

from teleclaude.api import todo_routes
from teleclaude.api.auth import CallerIdentity
from teleclaude.cli.telec.handlers import todo as todo_handlers
from teleclaude.core.db import Db
from teleclaude.core.db import _sessions as db_sessions_mod
from teleclaude.core.next_machine.rename import execute_todo_rename
from teleclaude.core.next_machine.unclaim import unclaim_todo_for_caller
from teleclaude.core.operation_caller_identity import reset_caller_session_id, set_caller_session_id
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_kind import TODO_KIND_CHANGE

pytestmark = pytest.mark.functional

_SLUG = "owned-todo"
_RENAMED_SLUG = "renamed-todo"
_OWNER_SESSION = "owner-session"
_OTHER_SESSION = "other-session"


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None]:
    monkeypatch.setattr(db_sessions_mod.event_bus, "emit", lambda *args, **kwargs: None)
    yield
    await close_todos_db_instances()


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _add_todo(
    todos_db: TodosDb,
    slug: str,
    *,
    active_runner: str | None = None,
    manually_started: bool = False,
    lifecycle_phase: LifecyclePhase = LifecyclePhase.PLAN_DRAFTING,
) -> None:
    await todos_db.add_to_todo(slug, lineage="human:test@example.com")
    state: dict[str, StateValue] = {
        "schema_version": 5,
        "kind": TODO_KIND_CHANGE,
        "phase": "in_progress",
        "lifecycle_phase": lifecycle_phase.value,
    }
    if active_runner is not None:
        state["active_runner"] = active_runner
        state["manually_started"] = manually_started
    await todos_db.write_state(slug, state)


async def _add_session(
    db: Db,
    project_root: Path,
    *,
    session_id: str,
    working_slug: str | None,
) -> None:
    await db.create_session(
        computer_name="test",
        tmux_session_name=f"tmux-{session_id}",
        last_input_origin="cli",
        title=session_id,
        session_id=session_id,
        project_path=str(project_root),
        working_slug=working_slug,
        emit_session_started=False,
    )


async def test_unclaim_clears_owned_active_runner_and_working_slug(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _SLUG, active_runner=_OWNER_SESSION, manually_started=True)
    daemon_db = Db(str(tmp_path / "daemon.db"))
    await daemon_db.initialize()
    await _add_session(daemon_db, project_root, session_id=_OWNER_SESSION, working_slug=_SLUG)

    result = await unclaim_todo_for_caller(
        daemon_db,
        slug=_SLUG,
        cwd=str(project_root),
        caller_session_id=_OWNER_SESSION,
    )

    assert result
    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state.get("active_runner") is None
    assert state.get("manually_started") is False
    session = await daemon_db.get_session(_OWNER_SESSION)
    assert session is not None
    assert session.working_slug is None


async def test_unclaim_refuses_foreign_live_claim_without_mutation(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _SLUG, active_runner=_OWNER_SESSION, manually_started=True)
    daemon_db = Db(str(tmp_path / "daemon.db"))
    await daemon_db.initialize()
    await _add_session(daemon_db, project_root, session_id=_OWNER_SESSION, working_slug=_SLUG)
    await _add_session(daemon_db, project_root, session_id=_OTHER_SESSION, working_slug=None)

    result = await unclaim_todo_for_caller(
        daemon_db,
        slug=_SLUG,
        cwd=str(project_root),
        caller_session_id=_OTHER_SESSION,
    )

    assert result == snapshot
    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state.get("active_runner") == _OWNER_SESSION
    session = await daemon_db.get_session(_OWNER_SESSION)
    assert session is not None
    assert session.working_slug == _SLUG


async def test_unclaim_without_owned_claim_is_idempotent(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _SLUG)
    daemon_db = Db(str(tmp_path / "daemon.db"))
    await daemon_db.initialize()
    await _add_session(daemon_db, project_root, session_id=_OTHER_SESSION, working_slug=None)

    result = await unclaim_todo_for_caller(
        daemon_db,
        slug=_SLUG,
        cwd=str(project_root),
        caller_session_id=_OTHER_SESSION,
    )

    assert result
    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state.get("active_runner") is None
    session = await daemon_db.get_session(_OTHER_SESSION)
    assert session is not None
    assert session.working_slug is None


def _identity(session_id: str) -> CallerIdentity:
    return CallerIdentity(
        session_id=session_id,
        system_role="worker",
        human_role=None,
        tmux_session_name=None,
    )


async def test_todo_update_route_unclaim_clears_owner_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _SLUG, active_runner=_OWNER_SESSION, manually_started=True)
    daemon_db = Db(str(tmp_path / "daemon.db"))
    await daemon_db.initialize()
    await _add_session(daemon_db, project_root, session_id=_OWNER_SESSION, working_slug=_SLUG)
    monkeypatch.setattr(todo_routes, "runtime_db", daemon_db)

    response = await todo_routes.todo_update(
        slug=_SLUG,
        unclaim=True,
        cwd=str(project_root),
        identity=_identity(_OWNER_SESSION),
    )

    assert isinstance(response, todo_routes._TodoUpdateResponse)
    assert response.unclaim
    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state.get("active_runner") is None
    session = await daemon_db.get_session(_OWNER_SESSION)
    assert session is not None
    assert session.working_slug is None


async def test_todo_update_route_unclaim_refuses_foreign_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _SLUG, active_runner=_OWNER_SESSION, manually_started=True)
    daemon_db = Db(str(tmp_path / "daemon.db"))
    await daemon_db.initialize()
    await _add_session(daemon_db, project_root, session_id=_OWNER_SESSION, working_slug=_SLUG)
    await _add_session(daemon_db, project_root, session_id=_OTHER_SESSION, working_slug=None)
    monkeypatch.setattr(todo_routes, "runtime_db", daemon_db)

    with pytest.raises(HTTPException) as exc_info:
        await todo_routes.todo_update(
            slug=_SLUG,
            unclaim=True,
            cwd=str(project_root),
            identity=_identity(_OTHER_SESSION),
        )

    assert {"status_code": exc_info.value.status_code, "detail": exc_info.value.detail} == snapshot
    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state.get("active_runner") == _OWNER_SESSION
    session = await daemon_db.get_session(_OWNER_SESSION)
    assert session is not None
    assert session.working_slug == _SLUG


def test_todo_update_cli_sends_unclaim(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_call = MagicMock(return_value={"status": "ok"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_call", tool_api_call)

    todo_handlers._handle_todo_update([_SLUG, "--unclaim"])

    assert tool_api_call.call_args.args[:2] == ("POST", "/todos/update")
    body = tool_api_call.call_args.kwargs["json_body"]
    assert body["slug"] == _SLUG
    assert body["unclaim"] is True
    assert Path(body["cwd"]) == project_root


class _ExecutingRenameService:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def submit_todo_rename(
        self,
        *,
        old_slug: str,
        new_slug: str,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> dict[str, str | None]:
        token = set_caller_session_id(caller_session_id)
        try:
            result = await execute_todo_rename(self._db, old_slug, new_slug, cwd)
        finally:
            reset_caller_session_id(token)
        return {"result": result, "client_request_id": client_request_id}


async def test_todo_update_unclaim_then_rename_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _SLUG, active_runner=_OWNER_SESSION, manually_started=True)
    daemon_db = Db(str(tmp_path / "daemon.db"))
    await daemon_db.initialize()
    await _add_session(daemon_db, project_root, session_id=_OWNER_SESSION, working_slug=_SLUG)
    monkeypatch.setattr(todo_routes, "runtime_db", daemon_db)
    monkeypatch.setattr(todo_routes, "get_operations_service", lambda: _ExecutingRenameService(daemon_db))

    response = await todo_routes.todo_update(
        slug=_SLUG,
        new_slug=_RENAMED_SLUG,
        unclaim=True,
        cwd=str(project_root),
        identity=_identity(_OWNER_SESSION),
    )

    assert isinstance(response, dict)
    assert response["result"]
    assert not await todos_db.slug_in_todo(_SLUG)
    assert await todos_db.slug_in_todo(_RENAMED_SLUG)
    state = await todos_db.read_state(_RENAMED_SLUG)
    assert state is not None
    assert state.get("active_runner") is None
    session = await daemon_db.get_session(_OWNER_SESSION)
    assert session is not None
    assert session.working_slug is None
