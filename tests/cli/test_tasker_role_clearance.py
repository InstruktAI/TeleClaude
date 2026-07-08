"""CLI-surface clearance for the tasker system role.

Tasker (dispatched via /next-prepare-task or /next-run-task) is otherwise a
Worker, but additionally may dispatch worker-lane sessions via `sessions run`.
It must never gain access to the state-machine-driving `todo prepare`/`todo
work` verbs, nor to `sessions revive` — that boundary has no other CLI-surface
test guarding it. The route-level HTTP enforcement is covered functionally by
`tests/agent_runtime/test_session_revival.py::test_tasker_caller_is_rejected_by_the_real_revive_route`.
"""

from __future__ import annotations

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
