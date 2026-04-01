"""State machine engine — pure target-based transitions with history.

The engine is pure: no I/O, no filesystem, no imports from state_io.
Persistence is the caller's concern.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine._types import StateValue

logger = get_logger(__name__)


@dataclass(frozen=True)
class TargetContext:
    """Context passed to on_enter handlers when targeting a state.

    Both paths are resolved once at engine entry — handlers consume, never derive.
    """

    worktree_path: str
    project_root: str
    slug: str
    actor_id: str
    at: str


type OnEnterFn = Callable[[dict[str, StateValue], TargetContext], dict[str, StateValue]]


@dataclass(frozen=True)
class State:
    """A named state with an optional on_enter handler."""

    name: str
    on_enter: OnEnterFn | None = None


@dataclass(frozen=True)
class StateMachine:
    """Pure state machine with ordered states, on_enter handlers, and history."""

    states: list[State] = field(default_factory=list)

    @property
    def state_names(self) -> list[str]:
        """Return ordered state names (used by _state_index for ordering queries)."""
        return [s.name for s in self.states]

    def target(
        self,
        snapshot: dict[str, StateValue],
        target_name: str,
        context: TargetContext,
    ) -> dict[str, StateValue]:
        """Move to any named state.

        Returns the updated snapshot (new dict, original not mutated).

        Algorithm:
        1. Validate target_name is a known state
        2. Deep-copy snapshot, set current, append history
        3. Call on_enter if present
        4. Return updated snapshot
        """
        # Validate target exists
        state_def = self._lookup_state(target_name)

        result = copy.deepcopy(snapshot)
        source = str(result.get("current", ""))

        # Already at target — idempotent no-op
        if source == target_name:
            logger.info(
                "target no-op: already at '%s'",
                target_name,
            )
            return result

        # Advance state
        result["current"] = target_name

        # Record history
        history = list(result.get("history", []))  # type: ignore[arg-type]
        history.append(
            {
                "source": source,
                "target": target_name,
                "by": context.actor_id,
                "at": context.at,
                "metadata": {},
            }
        )
        result["history"] = history

        # Call on_enter handler if present
        if state_def.on_enter is not None:
            result = state_def.on_enter(result, context)

        logger.info(
            "target: %s → %s (actor=%s)",
            source,
            target_name,
            context.actor_id,
        )
        return result

    def _lookup_state(self, name: str) -> State:
        """Find a state definition by name."""
        for s in self.states:
            if s.name == name:
                return s
        raise ValueError(f"unknown state: '{name}'")

    def _state_index(self, state: str) -> int:
        """Return the index of a state in the ordered states list."""
        try:
            return self.state_names.index(state)
        except ValueError:
            return -1
