"""Functional coverage for the run-session-with-command Codex loader rewrite."""

from __future__ import annotations

from collections.abc import Awaitable
from pathlib import Path

import pytest
from httpx import AsyncClient
from syrupy.assertion import SnapshotAssertion

from teleclaude.constants import ROLE_ORCHESTRATOR
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.models import SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.todos_db import get_todos_db
from teleclaude.paths import COMMANDS_DIR
from teleclaude.project_root import resolve_project_root
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import TodoState

_SPEC = "project/spec/feature/agent_runtime/run-session-with-command"

_PREPARE_COMMAND = "/next-prepare"
_INTEGRATE_COMMAND = "/next-integrate"
_REVIEW_COMMITS_COMMAND = "/next-review-commits"
_BUILD_COMMAND = "/next-build"
_COMMANDS_DIR_SENTINEL = "<COMMANDS_DIR>"
_DSD2_SLUG = "dsd2-slug"
_DSD2_HOLDER_ID = "holder-dsd2"


def _install_launch_intent_capture(monkeypatch: pytest.MonkeyPatch) -> list[SessionLaunchIntent | None]:
    """Capture the launch intent handed to bootstrap at the `/sessions/run` boundary.

    The fixture discards the bootstrap coroutine without awaiting it, so a coroutine
    body never runs. Record synchronously instead: replace the bootstrap with a plain
    callable that appends the intent and returns a throwaway coroutine for the queue to
    close.
    """
    captured: list[SessionLaunchIntent | None] = []

    def _capture_bootstrap(session_id: str, launch_intent: SessionLaunchIntent | None = None) -> Awaitable[None]:
        del session_id
        captured.append(launch_intent)

        async def _noop() -> None:
            return None

        return _noop()

    monkeypatch.setattr(get_command_service(), "_bootstrap_session", _capture_bootstrap)
    return captured


def _redact_commands_dir(message: str | None) -> str | None:
    """Replace the machine-specific commands directory so the prompt snapshots portably."""
    if message is None:
        return None
    return message.replace(str(COMMANDS_DIR), _COMMANDS_DIR_SENTINEL)


async def _run(api: AsyncClient, project: Path, *, command: str, args: str, agent: str) -> object:
    return await api.post(
        "/sessions/run",
        json={"command": command, "args": args, "project": str(project), "agent": agent},
    )


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CLR2")
async def test_codex_non_slug_bound_argless_produces_loader_message(
    api: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    """Codex argless lifecycle commands boot the loader, not a 400."""
    captured = _install_launch_intent_capture(monkeypatch)

    rendered: dict[str, str | None] = {}
    for command in (_PREPARE_COMMAND, _INTEGRATE_COMMAND, _REVIEW_COMMITS_COMMAND):
        captured.clear()
        response = await _run(api, tmp_path, command=command, args="", agent="codex")

        assert response.status_code == 200, response.text
        assert len(captured) == 1
        intent = captured[0]
        assert intent is not None
        assert intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
        rendered[command] = _redact_commands_dir(intent.message)

    assert rendered == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CLR1")
async def test_codex_slug_bound_argless_is_rejected(
    api: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    """Codex /next-build with empty args still fails the slug-bound guard with HTTP 400."""
    _install_launch_intent_capture(monkeypatch)

    response = await _run(api, tmp_path, command=_BUILD_COMMAND, args="", agent="codex")

    assert response.status_code == 400
    assert response.json() == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CLR3")
async def test_non_codex_agent_leaves_startup_message_unchanged(
    api: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-Codex agent dispatching /next-integrate keeps the raw command as its startup message."""
    captured = _install_launch_intent_capture(monkeypatch)

    response = await _run(api, tmp_path, command=_INTEGRATE_COMMAND, args="", agent="claude")

    assert response.status_code == 200, response.text
    assert len(captured) == 1
    intent = captured[0]
    assert intent is not None
    assert intent.message == _INTEGRATE_COMMAND


async def _create(api: AsyncClient, project: Path, *, message: str) -> object:
    """POST /sessions (the generic create door) with a slash-command message and no subdir."""
    return await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": str(project),
            "agent": "claude",
            "thinking_mode": "fast",
            "message": message,
        },
    )


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-DSD2")
async def test_generic_create_door_stamps_working_slug_from_message(api: AsyncClient, tmp_path: Path) -> None:
    """A repo-root manual /next-work <slug> create binds working_slug without a worktree subdir."""
    response = await _create(api, tmp_path, message=f"/next-work {_DSD2_SLUG}")

    assert response.status_code == 200, response.text
    session = await api.db.get_session(response.json()["session_id"])
    assert session is not None
    assert session.working_slug == _DSD2_SLUG


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-DSD2")
async def test_generic_create_door_leaves_working_slug_unset_for_slug_less_command(
    api: AsyncClient, tmp_path: Path
) -> None:
    """A slug-less lifecycle command such as /next-integrate stamps no working_slug."""
    response = await _create(api, tmp_path, message=_INTEGRATE_COMMAND)

    assert response.status_code == 200, response.text
    session = await api.db.get_session(response.json()["session_id"])
    assert session is not None
    assert session.working_slug is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-DSD2")
async def test_generic_create_door_refuses_duplicate_orchestrator_driver(
    api: AsyncClient, tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    """The create-door dedup guard fires for a message-derived working_slug, mirroring /sessions/run."""
    project = tmp_path / "dsd2-conflict"
    project.mkdir()
    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tmux-{_DSD2_HOLDER_ID}",
        last_input_origin="terminal",
        title=f"holder {_DSD2_SLUG}",
        session_id=_DSD2_HOLDER_ID,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(project),
        working_slug=_DSD2_SLUG,
        emit_session_started=False,
    )
    todos_db = await get_todos_db(resolve_project_root(project))
    await todos_db.add_to_todo(_DSD2_SLUG, after=None)
    await todos_db.write_state(
        _DSD2_SLUG,
        TodoState(
            schema_version=5,
            kind="change",
            lifecycle_phase=LifecyclePhase.PREPARED.value,
            active_runner=_DSD2_HOLDER_ID,
        ).model_dump(exclude_none=True),
    )

    response = await _create(api, project, message=f"/next-work {_DSD2_SLUG}")

    assert response.status_code == 409, response.text
    assert response.json() == snapshot
