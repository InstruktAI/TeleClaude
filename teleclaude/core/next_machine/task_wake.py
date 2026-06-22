"""Wake live task-run sessions for recurring schedules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.dates import task_schedule_due
from teleclaude.core.next_machine.kinds import KIND_TASK

logger = get_logger(__name__)


class RecurringTaskTodo(Protocol):
    @property
    def kind(self) -> str | None: ...

    @property
    def schedule(self) -> str | None: ...

    @property
    def active_runner(self) -> str | None: ...

    @property
    def task_plan_digest(self) -> str: ...

    @property
    def task_approved(self) -> bool: ...

    @property
    def task_approved_digest(self) -> str: ...


def is_recurring_schedule(schedule: str | None) -> bool:
    """Return whether a task schedule is recurring."""
    return bool(schedule and schedule.startswith("cron:"))


async def wake_due_recurring_tasks[T: RecurringTaskTodo](
    *,
    client: object,
    todos: Mapping[str, T],
    already_driven: Sequence[str],
    live_session_ids: set[str],
    trigger: str,
) -> list[str]:
    """Send a due-firing prompt to already-live recurring task sessions."""
    if trigger != "scheduler.tick.minute":
        return []
    woken: list[str] = []
    for slug in already_driven:
        todo = todos.get(slug)
        if (
            todo is None
            or todo.kind != KIND_TASK
            or not is_recurring_schedule(todo.schedule)
            or not todo.active_runner
            or todo.active_runner not in live_session_ids
            or not todo.task_plan_digest
            or not todo.task_approved
            or todo.task_approved_digest != todo.task_plan_digest
            or not task_schedule_due(todo.schedule)
        ):
            continue
        message = (
            f"Scheduled recurring firing is due for task `{slug}`. Execute the next firing from the "
            "current task-plan, append the result to the log, and stay alive for follow-up."
        )
        try:
            sent = await cast(Any, client).send_message(todo.active_runner, config.computer.name, message)
        except AttributeError:
            logger.warning("recurring task wake skipped: client cannot send messages", slug=slug)
            continue
        except Exception:
            logger.warning("recurring task wake failed", slug=slug, session_id=todo.active_runner, exc_info=True)
            continue
        if sent:
            woken.append(slug)
    return woken
