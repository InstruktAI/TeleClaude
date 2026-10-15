"""The refusal of a slug or kind update once the build of a todo has started."""

from __future__ import annotations

from typing import Final

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.core.workflow_machine.phase_reading import work_started
from teleclaude.types.todos import TodoState

BUILD_STARTED_REFUSAL: Final = "slug and kind updates are refused after build starts for '{slug}'"


class BuildAlreadyStarted(StateMutationError):
    """The todo's build has started, so its slug and kind no longer change."""


def refuse_if_build_started(slug: str, raw: dict[str, StateValue] | None) -> None:
    """Raise when the state shows work already begun; a missing row is left to the caller's own not-found path."""
    if raw is not None and work_started(TodoState.model_validate(raw)):
        raise BuildAlreadyStarted(BUILD_STARTED_REFUSAL.format(slug=slug))
