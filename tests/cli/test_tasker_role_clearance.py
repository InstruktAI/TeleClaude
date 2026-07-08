"""CLI-surface and route-clearance boundaries for the tasker system role.

Tasker (dispatched via /next-prepare-task or /next-run-task) is otherwise a
Worker, but additionally may dispatch worker-lane sessions via `sessions run`.
It must never gain access to the state-machine-driving `todo prepare`/`todo
work` verbs, nor to `sessions revive` — none of that has any other test
guarding it.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity, clearance_sessions_revive
from teleclaude.cli.telec.auth import is_command_allowed
from teleclaude.constants import ROLE_TASKER


def test_tasker_may_call_sessions_run() -> None:
    assert is_command_allowed("sessions run", ROLE_TASKER, None) is True


def test_tasker_may_not_drive_todo_prepare() -> None:
    assert is_command_allowed("todo prepare", ROLE_TASKER, None) is False


def test_tasker_may_not_drive_todo_work() -> None:
    assert is_command_allowed("todo work", ROLE_TASKER, None) is False


def test_tasker_may_not_call_sessions_revive() -> None:
    assert is_command_allowed("sessions revive", ROLE_TASKER, None) is False


@pytest.mark.asyncio
async def test_tasker_route_clearance_rejects_revive() -> None:
    """Route-level regression guard: `sessions revive` must clear on its own tool
    name, not `sessions run` — the latter is now tasker-permitted and a shared
    clearance dependency would silently let tasker through revive's API route too.
    """
    identity = CallerIdentity(
        session_id="tasker-session",
        system_role=ROLE_TASKER,
        human_role=None,
        tmux_session_name=None,
    )

    with pytest.raises(HTTPException) as exc:
        await clearance_sessions_revive(identity=identity)

    assert exc.value.status_code == 403
