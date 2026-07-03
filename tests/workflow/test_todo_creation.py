"""Functional tests bound to the workflow todo-creation spec."""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import TypedDict, TypeGuard, Unpack, cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from teleclaude.api import auth as auth_mod
from teleclaude.api import todo_routes
from teleclaude.api.auth import CallerIdentity, optional_caller_identity
from teleclaude.api_models import CreateSessionResponseDTO, TodoDumpRequest
from teleclaude.cli.api_client import RunSessionArgs
from teleclaude.cli.telec import main
from teleclaude.cli.telec.handlers import todo as todo_handlers
from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_TASK_PLAN,
    ROLE_ORCHESTRATOR,
    TodoStatus,
)
from teleclaude.core import db as db_mod
from teleclaude.core.command_handlers import _session as session_handler_mod
from teleclaude.core.command_handlers._session import create_session
from teleclaude.core.db import Db
from teleclaude.core.db._sync import resolve_session_principal
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.origins import InputOrigin
from teleclaude.core.todo import assemble_todo_from_db
from teleclaude.core.todos_db import (
    HolderWriteRefused,
    TodosDb,
    close_todos_db_instances,
    get_todos_db,
    todos_db_path,
)
from teleclaude.core.todos_db._show import ShowPayload, TodoShowPayload, assemble_show_payload
from teleclaude.events.cartridges import lifecycle_router
from teleclaude.events.cartridges.lifecycle_router import LifecycleRouterCartridge
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import PipelineContext
from teleclaude.types.commands import CreateSessionCommand
from teleclaude.types.todos import HoldAuditSource

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/todo-creation"
_WORKFLOW_TODO_CREATED = "workflow.todo.created"
_SOURCE = "api.todo.create"
_DOMAIN = "software-development"
_KIND_CHANGE = "change"
_KIND_BUG = "bug"
_KIND_TASK = "task"
_PARENT = "parent"
_CHILD = "child"
_KINDLESS = "kindless"
_PARKED = "parked-idea"
_HELD = "held-change"
_NEXT_PREPARE = "/next-prepare"
_NEXT_WORK = "/next-work"
_ANALYZE_TODO_INPUT = "/analyze-todo-input"
_CAPTURED_SESSION = "captured-session"


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _add_todo(
    todos_db: TodosDb,
    slug: str,
    *,
    lifecycle_phase: LifecyclePhase,
    after: list[str] | None = None,
    kind: str = _KIND_CHANGE,
) -> None:
    await todos_db.add_to_todo(slug, after=after)
    await todos_db.write_state(
        slug,
        {
            "schema_version": 4,
            "kind": kind,
            "phase": "pending",
            "lifecycle_phase": lifecycle_phase.value,
        },
    )


def _created_event(payload: Mapping[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event=_WORKFLOW_TODO_CREATED,
        source=_SOURCE,
        level=EventLevel.WORKFLOW,
        domain=_DOMAIN,
        payload=dict(payload),
    )


class _CapturingTelecAPIClient:
    calls: list[RunSessionArgs] = []

    async def connect(self) -> None:
        return None

    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> CreateSessionResponseDTO:
        self.calls.append(kwargs)
        return CreateSessionResponseDTO(
            status="success",
            session_id=_CAPTURED_SESSION,
            tmux_session_name="tmux-captured-session",
        )

    async def close(self) -> None:
        return None


class _EmittedEvent(TypedDict, total=False):
    payload: object


async def _noop_emit_event(**_kwargs: object) -> None:
    return None


def _is_todo_show_payload(payload: ShowPayload) -> TypeGuard[TodoShowPayload]:
    return payload.get("stage") != "holder"


@pytest.mark.spec(_SPEC, "UC-WTC1")
def test_create_help_exposes_canonical_kind_choices(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    snapshot: object,
) -> None:
    monkeypatch.setattr(sys, "argv", ["telec", "todo", "create", "--help"])

    main()

    captured = capsys.readouterr()
    # The hidden specialist `--hold` flag is suppressed from broad create help.
    assert "--hold" not in captured.out
    assert {"stdout": captured.out, "stderr": captured.err} == snapshot


@pytest.mark.spec(_SPEC, "UC-WTC2")
async def test_lifecycle_router_wake_up_evaluates_full_project_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    event_project = tmp_path / "event-project"
    env_project = tmp_path / "env-project"
    todos_db = await _project_db(event_project)
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", str(env_project))
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []
    event = _created_event(
        {
            "slug": _CHILD,
            "kind": _KIND_CHANGE,
            "pickup_requested": True,
            "lifecycle_phase": LifecyclePhase.DRAFT.value,
            "project_path": str(event_project),
        }
    )

    await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _NEXT_PREPARE
    assert call["args"] == _PARENT
    assert call["project_path"] == str(event_project)


@pytest.mark.spec(_SPEC, "UC-WTC3")
async def test_lifecycle_router_dispatches_deps_satisfied_create_from_event_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    event_project = tmp_path / "event-project"
    env_project = tmp_path / "env-project"
    event_db = await _project_db(event_project)
    await _add_todo(event_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    await _add_todo(event_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    env_db = await get_todos_db(env_project)
    await _add_todo(env_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await _add_todo(env_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", str(env_project))
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []
    event = _created_event(
        {
            "slug": _CHILD,
            "kind": _KIND_CHANGE,
            "pickup_requested": True,
            "lifecycle_phase": LifecyclePhase.DRAFT.value,
            "project_path": str(event_project),
        }
    )

    await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    assert [(call["command"], call["args"]) for call in _CapturingTelecAPIClient.calls] == [
        (_NEXT_WORK, _PARENT),
        (_NEXT_PREPARE, _CHILD),
    ]
    assert {call["project_path"] for call in _CapturingTelecAPIClient.calls} == {str(event_project)}


@pytest.mark.spec(_SPEC, "UC-WTC5")
async def test_kindless_create_persists_no_phase_and_dispatches_analyzer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []

    await todo_routes.todo_content_create(
        TodoDumpRequest(slug=_KINDLESS, content="Classify this raw dump.", cwd=str(project_root)),
        identity=None,
    )

    todos_db = await get_todos_db(project_root)
    state = await todos_db.read_state(_KINDLESS)
    assert state is not None
    assert state["kind"] is None
    assert "lifecycle_phase" not in state

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["kind"] is None
    assert payload["lifecycle_phase"] is None

    await LifecycleRouterCartridge().process(_created_event(payload), cast(PipelineContext, object()))

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _ANALYZE_TODO_INPUT
    assert call["args"] == _KINDLESS
    assert call["project_path"] == str(project_root)


@pytest.mark.spec(_SPEC, "UC-WTC11")
async def test_icebox_create_parks_todo_and_suppresses_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=_PARKED,
            content="Park this idea until promoted.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            icebox=True,
        ),
        identity=None,
    )

    todos_db = await get_todos_db(project_root)
    state = await todos_db.read_state(_PARKED)
    assert state is not None
    assert await todos_db.read_artifact(_PARKED, ARTIFACT_INPUT)

    [todo] = assemble_todo_from_db(str(project_root), include_icebox=True, icebox_only=True)
    assert todo.slug == _PARKED
    assert todo.status == TodoStatus.ICEBOX
    assert todo.ready_since is None

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["pickup_requested"] is False

    await LifecycleRouterCartridge().process(_created_event(payload), cast(PipelineContext, object()))
    assert _CapturingTelecAPIClient.calls == []


@pytest.mark.spec(_SPEC, "UC-WTC18")
def test_create_hold_flag_sends_hold_in_request_body(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The hidden `--hold` flag parses through the CLI handler into hold=True on the request body."""
    invocation_cwd = tmp_path / "invocation"
    invocation_cwd.mkdir()
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: invocation_cwd)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_todo_create([_HELD, "Live-human prepare orchestration.", "--kind", _KIND_CHANGE, "--hold"])

    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert json_body["hold"] is True


@pytest.mark.spec(_SPEC, "UC-WTC18")
async def test_hold_create_writes_active_held_state_and_exposes_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    monkeypatch.setattr(todo_routes, "emit_event", _noop_emit_event)

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=_HELD,
            content="Live-human prepare orchestration.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            hold=True,
        ),
        identity=None,
    )

    todos_db = await get_todos_db(project_root)
    # Active roadmap row (not iceboxed) + input artifact written normally. The
    # default projection excludes the icebox, so the held todo surfacing here
    # proves its roadmap status is active, not parked.
    assert await todos_db.read_artifact(_HELD, ARTIFACT_INPUT)
    [todo] = assemble_todo_from_db(str(project_root))
    assert todo.slug == _HELD
    assert todo.status != TodoStatus.ICEBOX
    # The held projection mirrors update-created holds.
    assert todo.hold is True
    assert todo.held is True
    assert todo.hold_source == HoldAuditSource.CREATION.value

    # Persisted state carries the creation-sourced hold brake.
    state = await todos_db.read_state(_HELD)
    assert state is not None
    assert state["hold"] is True
    hold_audit = state["hold_audit"]
    assert isinstance(hold_audit, dict)
    assert hold_audit["source"] == HoldAuditSource.CREATION.value

    # `telec todo show` exposes the held state through the same state block.
    payload = await assemble_show_payload(todos_db, _HELD)
    assert payload is not None
    assert _is_todo_show_payload(payload)
    state_block = payload["state"]
    assert state_block["hold"] is True
    audit_block = state_block["hold_audit"]
    assert isinstance(audit_block, dict)
    assert audit_block["source"] == HoldAuditSource.CREATION.value


@pytest.mark.spec(_SPEC, "UC-WTC19")
async def test_hold_create_suppresses_auto_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=_HELD,
            content="Live-human prepare orchestration.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            hold=True,
        ),
        identity=None,
    )

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["pickup_requested"] is False

    # The router consumes the held-create event without dispatching a session.
    await LifecycleRouterCartridge().process(_created_event(payload), cast(PipelineContext, object()))
    assert _CapturingTelecAPIClient.calls == []


@pytest.mark.spec(_SPEC, "UC-WTC20")
async def test_hold_and_icebox_are_mutually_exclusive_at_create(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)

    with pytest.raises(HTTPException) as exc:
        await todo_routes.todo_content_create(
            TodoDumpRequest(
                slug=_HELD,
                content="Cannot be both.",
                kind=_KIND_CHANGE,
                cwd=str(project_root),
                hold=True,
                icebox=True,
            ),
            identity=None,
        )

    assert exc.value.status_code == 400
    # The diagnostic names the mutually exclusive flags (snapshot is the contract).
    assert exc.value.detail == snapshot
    # Nothing was written: no row, no state, no event.
    assert emitted == []
    assert assemble_todo_from_db(str(project_root), include_icebox=True) == []


@pytest.mark.spec(_SPEC, "UC-WTC12")
async def test_group_create_attaches_child_and_derives_parent_holder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)

    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await todos_db.write_artifact(_PARENT, ARTIFACT_INPUT, f"# {_PARENT} — Input\n\nParent scope.\n", updated_by="test")
    parent_architecture = f"# {_PARENT} — Architecture\n\nDesign notes.\n"
    await todos_db.write_artifact(_PARENT, ARTIFACT_ARCHITECTURE, parent_architecture, updated_by="test")

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=_CHILD,
            content="Grouped child created complete.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            group=_PARENT,
        ),
        identity=None,
    )

    child_state = await todos_db.read_state(_CHILD)
    assert child_state is not None
    [child] = [t for t in assemble_todo_from_db(str(project_root), include_icebox=True) if t.slug == _CHILD]
    assert child.group == _PARENT

    assert await todos_db.is_holder(_PARENT) is True
    # todo_state stripped; all artifacts retained as frozen evidence.
    assert await todos_db.read_state(_PARENT) is None
    assert await todos_db.read_artifact(_PARENT, ARTIFACT_INPUT)
    assert await todos_db.read_artifact(_PARENT, ARTIFACT_ARCHITECTURE) == parent_architecture

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["slug"] == _CHILD


@pytest.mark.spec(_SPEC, "UC-WTC16")
async def test_group_create_preserves_prepared_artifacts_as_frozen_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Grouping a fully-prepared parent succeeds; its artifacts survive as frozen, read-only evidence."""
    project_root = tmp_path / "project"

    async def _capture_emit_event(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)

    parent_input = f"# {_PARENT} — Input\n\nParent scope.\n"
    parent_plan_v1 = f"# {_PARENT} — Implementation Plan\n\nDraft v1.\n"
    parent_plan_v2 = f"# {_PARENT} — Implementation Plan\n\nRevised v2, prepared work that must survive.\n"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await todos_db.write_artifact(_PARENT, ARTIFACT_INPUT, parent_input, updated_by="test")
    await todos_db.write_artifact(_PARENT, ARTIFACT_IMPLEMENTATION_PLAN, parent_plan_v1, updated_by="test")
    await todos_db.write_artifact(_PARENT, ARTIFACT_IMPLEMENTATION_PLAN, parent_plan_v2, updated_by="test")

    # Grouping a fully-prepared parent now succeeds — nothing is shredded.
    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=_CHILD,
            content="Grouped child created complete.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            group=_PARENT,
        ),
        identity=None,
    )

    assert await todos_db.is_holder(_PARENT) is True
    assert await todos_db.read_state(_PARENT) is None
    # Both artifacts survive byte-for-byte as frozen evidence.
    assert await todos_db.read_artifact(_PARENT, ARTIFACT_INPUT) == parent_input
    assert await todos_db.read_artifact(_PARENT, ARTIFACT_IMPLEMENTATION_PLAN) == parent_plan_v2
    # Version history survives intact.
    plan_versions = await todos_db.artifact_versions(_PARENT, ARTIFACT_IMPLEMENTATION_PLAN)
    assert {version["content"] for version in plan_versions} == {parent_plan_v1, parent_plan_v2}
    # The child row was created.
    assert await todos_db.read_state(_CHILD) is not None

    # The evidence is read-only: a subsequent API write is refused with a 409...
    with pytest.raises(HTTPException) as write_exc:
        await todo_routes.write_artifact(
            slug=_PARENT,
            name=ARTIFACT_IMPLEMENTATION_PLAN,
            content="# attempted overwrite\n",
            cwd=str(project_root),
        )
    assert write_exc.value.status_code == 409

    # ...and a subsequent API remove is refused with a 409, not a misleading 404.
    with pytest.raises(HTTPException) as remove_exc:
        await todo_routes.remove_artifact(
            slug=_PARENT,
            name=ARTIFACT_IMPLEMENTATION_PLAN,
            cwd=str(project_root),
        )
    assert remove_exc.value.status_code == 409

    # The preserved bytes and version history are left intact after both refusals.
    assert await todos_db.read_artifact(_PARENT, ARTIFACT_IMPLEMENTATION_PLAN) == parent_plan_v2
    plan_versions_after = await todos_db.artifact_versions(_PARENT, ARTIFACT_IMPLEMENTATION_PLAN)
    assert {version["content"] for version in plan_versions_after} == {parent_plan_v1, parent_plan_v2}


async def test_holder_transition_leaves_delivered_same_slug_history_intact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A delivered row sharing the live parent's slug keeps its own state and artifacts untouched."""
    project_root = tmp_path / "project"

    async def _capture_emit_event(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)

    todos_db = await _project_db(project_root)

    # A prior incarnation of the slug: prepared, then delivered — its own row of history.
    delivered_architecture = f"# {_PARENT} — Architecture\n\nDelivered history.\n"
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await todos_db.write_artifact(_PARENT, ARTIFACT_ARCHITECTURE, delivered_architecture, updated_by="test")
    await todos_db.deliver(_PARENT, commit="deadbeef")

    # A fresh live incarnation of the same slug.
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    live_input = f"# {_PARENT} — Input\n\nFresh scope.\n"
    await todos_db.write_artifact(_PARENT, ARTIFACT_INPUT, live_input, updated_by="test")

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=_CHILD,
            content="Grouped child created complete.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            group=_PARENT,
        ),
        identity=None,
    )

    # The live row became a holder with its own state stripped.
    assert await todos_db.is_holder(_PARENT) is True
    assert await todos_db.read_state(_PARENT) is None
    assert await todos_db.read_artifact(_PARENT, ARTIFACT_INPUT) == live_input

    # The delivered row's own state and artifact were never touched by the strip.
    db_path = todos_db_path(project_root)
    conn = sqlite3.connect(str(db_path))
    try:
        delivered_row = conn.execute(
            "SELECT id FROM todo WHERE slug = ? AND status = 'delivered'", (_PARENT,)
        ).fetchone()
        assert delivered_row is not None
        delivered_row_id = delivered_row[0]
        state_row = conn.execute("SELECT state FROM todo_state WHERE id = ?", (delivered_row_id,)).fetchone()
        assert state_row is not None
        artifact_row = conn.execute(
            "SELECT content FROM todo_artifacts WHERE id = ? AND name = ?",
            (delivered_row_id, ARTIFACT_ARCHITECTURE),
        ).fetchone()
        assert artifact_row is not None
        assert artifact_row[0] == delivered_architecture
    finally:
        conn.close()


@pytest.mark.spec(_SPEC, "UC-WTC15")
async def test_holder_artifact_write_returns_clean_409_not_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: object,
) -> None:
    """A write to a holder is refused with a clean 409 (and a typed db error), never a raw 500."""
    project_root = tmp_path / "project"

    async def _capture_emit_event(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)

    parent_input = f"# {_PARENT} — Input\n\nParent scope.\n"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await todos_db.write_artifact(_PARENT, ARTIFACT_INPUT, parent_input, updated_by="test")
    # The first grouped child turns the parent into a structural holder.
    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=_CHILD,
            content="Grouped child created complete.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            group=_PARENT,
        ),
        identity=None,
    )

    assert await todos_db.is_holder(_PARENT) is True

    # API surface: a holder write returns a clean 409, not a raw 500.
    with pytest.raises(HTTPException) as exc:
        await todo_routes.write_artifact(
            slug=_PARENT,
            name=ARTIFACT_IMPLEMENTATION_PLAN,
            content=f"# {_PARENT} — Implementation Plan\n",
            cwd=str(project_root),
        )
    assert exc.value.status_code == 409
    # The refusal detail is the contract: structural holder, write-to-children directive.
    assert exc.value.detail == snapshot

    # DB surface: the refusal is the typed HolderWriteRefused (a ValueError subclass) —
    # this is what proves the 409 above is the holder path, not another conflict.
    with pytest.raises(HolderWriteRefused):
        await todos_db.write_artifact(_PARENT, ARTIFACT_IMPLEMENTATION_PLAN, "# plan\n", updated_by="test")

    # The holder's frozen input survives the refused write byte-for-byte.
    assert await todos_db.read_artifact(_PARENT, ARTIFACT_INPUT) == parent_input


@pytest.mark.spec(_SPEC, "UC-WTC13")
async def test_project_root_create_targets_explicit_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invocation_cwd = tmp_path / "invocation"
    target_project = tmp_path / "other-project"
    invocation_cwd.mkdir()
    target_project.mkdir()

    # CLI handler maps --project-root to the request cwd, not the invocation cwd.
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: invocation_cwd)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_todo_create(
        ["remote-task", "Targeted create.", "--kind", _KIND_CHANGE, "--project-root", str(target_project)]
    )

    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert Path(json_body["cwd"]) == target_project

    # Route honors the supplied cwd: the todo and its event land in the targeted project.
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug="remote-task",
            content="Targeted create.",
            kind=_KIND_CHANGE,
            cwd=str(target_project),
        ),
        identity=None,
    )

    target_db = await get_todos_db(target_project)
    assert await target_db.read_state("remote-task") is not None
    invocation_db = await get_todos_db(invocation_cwd)
    assert await invocation_db.read_state("remote-task") is None
    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["project_path"] == str(target_project)


@pytest.mark.spec(_SPEC, "UC-WTC14")
@pytest.mark.parametrize("retired_field", ["release", "silent"])
def test_retired_create_parking_fields_are_rejected(retired_field: str) -> None:
    with pytest.raises(ValidationError):
        TodoDumpRequest.model_validate(
            {
                "slug": "rejected",
                "content": "Stale client body.",
                "kind": _KIND_CHANGE,
                retired_field: True,
            }
        )


@pytest.mark.spec(_SPEC, "UC-WTC14")
def test_hold_create_field_is_accepted() -> None:
    """`hold` is no longer a retired field — it is the hidden create-time dispatch brake."""
    request = TodoDumpRequest.model_validate(
        {
            "slug": _HELD,
            "content": "Live-human prepare orchestration.",
            "kind": _KIND_CHANGE,
            "hold": True,
        }
    )
    assert request.hold is True


@pytest.mark.spec(_SPEC, "UC-WTC4")
async def test_lifecycle_router_dispatches_prepare_for_bug_in_diagnose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    event_project = tmp_path / "event-project"
    env_project = tmp_path / "env-project"
    event_db = await _project_db(event_project)
    await _add_todo(event_db, _CHILD, lifecycle_phase=LifecyclePhase.DIAGNOSE, kind=_KIND_BUG)
    await get_todos_db(env_project)
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", str(env_project))
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []
    event = _created_event(
        {
            "slug": _CHILD,
            "kind": _KIND_BUG,
            "pickup_requested": True,
            "lifecycle_phase": LifecyclePhase.DIAGNOSE.value,
            "project_path": str(event_project),
        }
    )

    await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _NEXT_PREPARE
    assert call["args"] == _CHILD


async def test_create_with_plan_seeds_plan_drafting_and_dispatches_prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: object,
) -> None:
    event_project = tmp_path / "event-project"
    env_project = tmp_path / "env-project"
    await _project_db(event_project)
    await get_todos_db(env_project)
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", str(env_project))
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []

    slug = "seeded-change"
    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=slug,
            content="Step 1: do the thing.",
            kind=_KIND_CHANGE,
            cwd=str(event_project),
            plan=True,
        ),
        identity=None,
    )

    todos_db = await get_todos_db(event_project)
    # The supplied content lands as the implementation-plan artifact (not input),
    # written under the "# <slug> — Implementation Plan" header. Snapshot the
    # exact body so a dropped header or substituted/placeholder content fails.
    plan_body = await todos_db.read_artifact(slug, ARTIFACT_IMPLEMENTATION_PLAN)
    assert plan_body == snapshot
    state = await todos_db.read_state(slug)
    assert state is not None
    writer = StateWriter(state)
    assert writer.state.lifecycle_phase == LifecyclePhase.PLAN_DRAFTING.value
    assert writer.state.artifacts.implementation_plan.seeded is True
    # The seed is not auto-approved: plan-review stays unstamped (empty verdict).
    assert not writer.state.plan_review.verdict

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["kind"] == _KIND_CHANGE
    assert payload["lifecycle_phase"] == LifecyclePhase.PLAN_DRAFTING.value
    assert payload["pickup_requested"] is True
    payload["project_path"] = str(event_project)

    await LifecycleRouterCartridge().process(_created_event(payload), cast(PipelineContext, object()))

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _NEXT_PREPARE
    assert call["args"] == slug
    assert call["project_path"] == str(event_project)


@pytest.mark.spec(_SPEC, "UC-WTC6")
async def test_create_task_enters_task_plan_drafting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)
    monkeypatch.setattr(todo_routes, "emit_event", _noop_emit_event)

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug="bare-task",
            content="Notify the team.",
            kind=_KIND_TASK,
            cwd=str(project_root),
        ),
        identity=None,
    )

    todos_db = await get_todos_db(project_root)
    state = await todos_db.read_state("bare-task")
    assert state is not None
    assert state["kind"] == _KIND_TASK
    assert state["lifecycle_phase"] == LifecyclePhase.TASK_PLAN_DRAFTING.value
    assert await todos_db.artifact_exists("bare-task", ARTIFACT_INPUT)
    assert not await todos_db.artifact_exists("bare-task", ARTIFACT_TASK_PLAN)


@pytest.mark.spec(_SPEC, "UC-WTC8")
async def test_create_task_with_plan_writes_pre_authorized_task_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)
    monkeypatch.setattr(todo_routes, "emit_event", _noop_emit_event)

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug="planned-task",
            content="1. Check the deployment.",
            kind=_KIND_TASK,
            cwd=str(project_root),
            plan=True,
        ),
        identity=_human_identity(),
    )

    todos_db = await get_todos_db(project_root)
    task_plan_digest = await todos_db.artifact_digest("planned-task", ARTIFACT_TASK_PLAN)
    state = await todos_db.read_state("planned-task")
    assert state is not None
    writer = StateWriter(state)
    assert writer.state.lifecycle_phase == LifecyclePhase.PREPARED.value
    assert writer.state.approvals.task_approved.approved is True
    assert writer.state.approvals.task_approved.approved_digest == task_plan_digest
    assert writer.state.artifacts.task_plan.digest == task_plan_digest


@pytest.mark.spec(_SPEC, "UC-WTC7")
async def test_create_task_refuses_schedule_with_dependencies(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    with pytest.raises(HTTPException) as exc_info:
        await todo_routes.todo_content_create(
            TodoDumpRequest(
                slug="conflicted-task",
                content="Run later.",
                kind=_KIND_TASK,
                after=["parent"],
                schedule="2099-01-01T00:00:00Z",
                cwd=str(project_root),
            ),
            identity=None,
        )

    assert exc_info.value.status_code == 400
    todos_db = await get_todos_db(project_root)
    assert await todos_db.read_state("conflicted-task") is None


@pytest.mark.spec(_SPEC, "UC-WTC7")
async def test_create_task_persists_recurring_schedule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshot: object
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)
    monkeypatch.setattr(todo_routes, "emit_event", _noop_emit_event)

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug="recurring-task",
            content="Run every Sunday morning.",
            kind=_KIND_TASK,
            schedule="cron:15 9 * * 7",
            cwd=str(project_root),
        ),
        identity=None,
    )

    todos_db = await get_todos_db(project_root)
    assert await todos_db.get_schedule("recurring-task") == snapshot


@pytest.mark.spec(_SPEC, "UC-WTC7")
async def test_create_task_rejects_malformed_recurring_schedule(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    with pytest.raises(HTTPException) as exc_info:
        await todo_routes.todo_content_create(
            TodoDumpRequest(
                slug="bad-recurring-task",
                content="Run on an impossible weekday.",
                kind=_KIND_TASK,
                schedule="cron:15 9 * * 8",
                cwd=str(project_root),
            ),
            identity=None,
        )

    assert exc_info.value.status_code == 400
    todos_db = await get_todos_db(project_root)
    assert await todos_db.read_state("bad-recurring-task") is None


_HUMAN_EMAIL = "alice@example.com"
_HUMAN_PRINCIPAL = f"human:{_HUMAN_EMAIL}"
_ROOT_EMAIL = "root@example.com"
_ROOT_PRINCIPAL = f"human:{_ROOT_EMAIL}"
_HUMAN_SLUG = "human-owned"
_SYSTEM_SLUG = "system-owned"
_HUMAN_SESSION = "sess-human"
_SYSTEM_SESSION = "sess-system"
_FAIL_SESSION = "sess-fail"
_SYSTEM_PRINCIPAL = f"system:{_SYSTEM_SESSION}"
_LEGACY_SLUG = "legacy-todo"
_LEGACY_DESC = "Pre-column row."
_AGENT_SESSION_ID = "agent-session"
_AGENT_SESSION_PRINCIPAL = f"session:{_AGENT_SESSION_ID}"


def _human_identity(email: str = _HUMAN_EMAIL) -> CallerIdentity:
    return CallerIdentity(
        session_id="",
        system_role=None,
        human_role="admin",
        tmux_session_name=None,
        email=email,
    )


def _agent_identity(principal: str | None) -> CallerIdentity:
    return CallerIdentity(
        session_id=_AGENT_SESSION_ID,
        system_role="worker",
        human_role=None,
        tmux_session_name=None,
        principal=principal,
    )


async def _create_via_route(
    project_root: Path,
    slug: str,
    identity: CallerIdentity | None,
    monkeypatch: pytest.MonkeyPatch,
) -> _EmittedEvent:
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    await todo_routes.todo_content_create(
        TodoDumpRequest(slug=slug, content="Lineage content.", kind=_KIND_CHANGE, cwd=str(project_root)),
        identity=identity,
    )
    [event_kwargs] = emitted
    return event_kwargs


@pytest.mark.spec(_SPEC, "UC-WTC8")
async def test_human_create_records_recovers_and_emits_creator_principal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    event_kwargs = await _create_via_route(project_root, "owned-change", _human_identity(), monkeypatch)

    # Persisted on the todo entry and recoverable from the record for later audit.
    todos_db = await get_todos_db(project_root)
    assert await todos_db.read_created_by_principal("owned-change") == _HUMAN_PRINCIPAL
    [row] = [r for r in await todos_db.list_todo() if r["slug"] == "owned-change"]
    assert row["created_by_principal"] == _HUMAN_PRINCIPAL

    # Emitted on workflow.todo.created with the same persisted owner.
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["created_by_principal"] == _HUMAN_PRINCIPAL


@pytest.mark.spec(_SPEC, "UC-WTC9")
async def test_agent_with_human_root_create_records_chain_root_human(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    # An agent session whose own resolved principal is the chain-root human.
    await _create_via_route(project_root, "agent-owned", _agent_identity(_ROOT_PRINCIPAL), monkeypatch)

    todos_db = await get_todos_db(project_root)
    # Records the chain-root human, not the agent session id.
    assert await todos_db.read_created_by_principal("agent-owned") == _ROOT_PRINCIPAL


@pytest.mark.spec(_SPEC, "UC-WTC21")
async def test_agent_with_human_root_records_both_agent_and_principal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    await _create_via_route(project_root, "agent-and-human", _agent_identity(_ROOT_PRINCIPAL), monkeypatch)

    todos_db = await get_todos_db(project_root)
    # Both axes are recoverable from the todo record, never one in place of the other.
    assert await todos_db.read_created_by_principal("agent-and-human") == _ROOT_PRINCIPAL
    assert await todos_db.read_created_by_agent("agent-and-human") == _AGENT_SESSION_PRINCIPAL
    [row] = [r for r in await todos_db.list_todo() if r["slug"] == "agent-and-human"]
    assert row["created_by_principal"] == _ROOT_PRINCIPAL
    assert row["created_by_agent"] == _AGENT_SESSION_PRINCIPAL


@pytest.mark.spec(_SPEC, "UC-WTC22")
async def test_autonomous_agent_create_records_agent_with_no_human_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    # An agent filing autonomously: no chain-root human resolves.
    event_kwargs = await _create_via_route(project_root, "autonomous-agent", _agent_identity(None), monkeypatch)

    todos_db = await get_todos_db(project_root)
    assert await todos_db.read_created_by_agent("autonomous-agent") == _AGENT_SESSION_PRINCIPAL
    assert await todos_db.read_created_by_principal("autonomous-agent") is None

    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["created_by_agent"] == _AGENT_SESSION_PRINCIPAL


@pytest.mark.spec(_SPEC, "UC-WTC23")
async def test_direct_human_terminal_create_records_no_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    await _create_via_route(project_root, "human-terminal", _human_identity(), monkeypatch)

    todos_db = await get_todos_db(project_root)
    assert await todos_db.read_created_by_agent("human-terminal") is None
    assert await todos_db.read_created_by_principal("human-terminal") == _HUMAN_PRINCIPAL


@pytest.mark.spec(_SPEC, "UC-WTC8")
async def test_create_capture_is_non_gating_in_multi_user_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    # Multi-user mode: a header-less caller makes verify_caller raise the
    # "login required" 401. optional_caller_identity must swallow it to None
    # so the open create route is never converted into a rejection.
    monkeypatch.setattr(auth_mod, "_requires_terminal_login", lambda: True)
    resolved = await optional_caller_identity()
    assert resolved is None

    event_kwargs = await _create_via_route(project_root, "anon-change", resolved, monkeypatch)

    # The create still succeeds and stores None — capture never gates.
    todos_db = await get_todos_db(project_root)
    assert await todos_db.read_state("anon-change") is not None
    assert await todos_db.read_created_by_principal("anon-change") is None
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["created_by_principal"] is None


async def _dispatch_runner_session(
    runtime_db: Db,
    project_root: Path,
    slug: str,
    session_id: str,
) -> object:
    """Drive create_session as the runner would: no human caller, slug-bound,
    system-role set. Returns the persisted session row."""
    await create_session(
        CreateSessionCommand(
            project_path=str(project_root),
            origin=InputOrigin.TERMINAL.value,
            session_id=session_id,
            working_slug=slug,
            system_role=ROLE_ORCHESTRATOR,
            headless=True,
            skip_listener_registration=True,
        ),
        cast("object", None),  # client is unused by the handler
    )
    return await runtime_db.get_session(session_id)


@pytest.mark.spec(_SPEC, "UC-WTC10")
async def test_runner_dispatched_session_inherits_owning_human(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_HUMAN_SLUG, created_by_principal=_HUMAN_PRINCIPAL)
    await todos_db.add_to_todo(_SYSTEM_SLUG, created_by_principal="system:some-session")

    runtime_db = Db(":memory:")
    await runtime_db.initialize()
    monkeypatch.setattr(db_mod, "db", runtime_db)
    monkeypatch.setattr(session_handler_mod, "db", runtime_db)

    # Human-owned todo: the runner-dispatched session resolves to the human root.
    human_session = await _dispatch_runner_session(runtime_db, project_root, _HUMAN_SLUG, _HUMAN_SESSION)
    assert human_session is not None
    principal, _role = resolve_session_principal(human_session)
    assert principal == _HUMAN_PRINCIPAL
    # Authorization band is untouched — lineage is audit-only.
    assert human_session.system_role == ROLE_ORCHESTRATOR

    # System-owned todo: no human root to inherit; resolves to system:<session>.
    system_session = await _dispatch_runner_session(runtime_db, project_root, _SYSTEM_SLUG, _SYSTEM_SESSION)
    assert system_session is not None
    system_principal, _ = resolve_session_principal(system_session)
    assert system_principal == _SYSTEM_PRINCIPAL


# Pre-column ``todo`` table: every column the substrate carried right before
# created_by_principal was introduced (post-rename, post-tombstone migrations).
_OLD_SHAPE_TODO_DDL = """
CREATE TABLE todo (
    id TEXT PRIMARY KEY, slug TEXT NOT NULL, ready_since TEXT, group_slug TEXT,
    description TEXT, status TEXT NOT NULL DEFAULT 'active', delivered_at TEXT,
    delivered_commit TEXT, children TEXT, removed_at TEXT, prev_status TEXT,
    removed_deps TEXT, pending_purge_paths TEXT, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


@pytest.mark.spec(_SPEC, "UC-WTC8")
async def test_old_shape_todo_row_upgrades_with_null_creator_principal(tmp_path: Path) -> None:
    """Golden old-shape fixture: a pre-column ``todo`` row survives the additive
    migration intact, reading back ``created_by_principal is None``."""
    project_root = tmp_path / "project"
    db_path = todos_db_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    await close_todos_db_instances()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_OLD_SHAPE_TODO_DDL)
        conn.execute(
            "INSERT INTO todo (id, slug, status, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "row-1",
                _LEGACY_SLUG,
                TodoStatus.ACTIVE.value,
                _LEGACY_DESC,
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Bootstrap runs the additive migration; the existing row loads through the
    # current TodoRow shape with the new field defaulted to None, intact otherwise.
    todos_db = await get_todos_db(project_root)
    [row] = await todos_db.list_todo()
    assert row["slug"] == _LEGACY_SLUG
    assert row["status"] == TodoStatus.ACTIVE.value
    assert row["description"] == _LEGACY_DESC
    assert row["created_by_principal"] is None


@pytest.mark.spec(_SPEC, "UC-WTC10")
async def test_runner_dispatch_stops_when_owner_read_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed owner read for a slug-bound runner session surfaces and stops
    creation — never silently degrades the required human root to system:<session>."""
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_HUMAN_SLUG, created_by_principal=_HUMAN_PRINCIPAL)

    runtime_db = Db(":memory:")
    await runtime_db.initialize()
    monkeypatch.setattr(db_mod, "db", runtime_db)
    monkeypatch.setattr(session_handler_mod, "db", runtime_db)

    async def _raise(_self: TodosDb, _slug: str) -> str | None:
        raise RuntimeError("owner read failed")

    monkeypatch.setattr(TodosDb, "read_created_by_principal", _raise)

    with pytest.raises(RuntimeError):
        await _dispatch_runner_session(runtime_db, project_root, _HUMAN_SLUG, _FAIL_SESSION)
    # No mis-attributed session row was persisted.
    assert await runtime_db.get_session(_FAIL_SESSION) is None
