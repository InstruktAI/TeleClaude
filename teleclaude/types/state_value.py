"""Recursive JSON-shaped type alias for todo state values.

Lives at the ``teleclaude.types`` boundary so that low-level typed models
(e.g. :class:`teleclaude.types.todos.TodoState`) can refer to it without
pulling in feature packages like ``teleclaude.core.next_machine``. The
next-machine package re-exports these names from
``teleclaude.core.next_machine._types`` for backward compatibility.
"""

from __future__ import annotations

type StateScalar = str | bool | int | None
type StateValue = StateScalar | list[StateValue] | dict[str, StateValue]

__all__ = ["StateScalar", "StateValue"]
