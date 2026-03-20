"""State machine engine — pure transitions with history, guards, and rewind.

The engine is pure: no I/O, no filesystem, no imports from state_io.
Persistence is the caller's concern.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NotRequired, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine._types import StateValue

logger = get_logger(__name__)


class TransitionContext(TypedDict):
    """Context passed to guard and action callables during a transition."""

    actor_id: str
    at: NotRequired[str]
    metadata: NotRequired[dict[str, StateValue]]


# Callable types for transition guards and actions
type ActionCallable = Callable[[dict[str, StateValue], TransitionContext], dict[str, StateValue]]
type GuardCallable = Callable[[dict[str, StateValue], TransitionContext], bool]


class TransitionRejected(Exception):
    """Raised when a transition cannot fire from the current state."""

    def __init__(self, *, current: str, transition: str, required_sources: set[str]) -> None:
        self.current = current
        self.transition = transition
        self.required_sources = required_sources
        super().__init__(
            f"transition '{transition}' rejected: current='{current}', required one of {sorted(required_sources)}"
        )


class RewindRejected(Exception):
    """Raised when rewind is not possible (empty history)."""

    def __init__(self, *, current: str) -> None:
        self.current = current
        super().__init__(f"rewind rejected: no history to rewind (current='{current}')")


@dataclass(frozen=True)
class TransitionDefinition:
    """A named transition between states."""

    name: str
    sources: set[str]
    target: str
    guard: GuardCallable | None = None
    action: ActionCallable | None = None


@dataclass(frozen=True)
class StateMachine:
    """Pure state machine with ordered states, guarded transitions, and history."""

    states: list[str]
    transitions: list[TransitionDefinition] = field(default_factory=list)

    def fire(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        snapshot: dict[str, StateValue],
        transition: str,
        actor_id: str,
        at: str,
        metadata: dict[str, StateValue] | None = None,
    ) -> dict[str, StateValue]:
        """Fire a named transition.

        Returns the updated snapshot (new dict, original not mutated).

        Algorithm:
        1. Current in sources → fire (guard → action → update current + history)
        2. Current already past target (by state order) → no-op
        3. Otherwise → TransitionRejected
        """
        defn = self._lookup(transition)
        result = copy.deepcopy(snapshot)
        current = str(result.get("current", ""))

        # Case 1: current is in the transition's source states — fire it
        if current in defn.sources:
            context = TransitionContext(actor_id=actor_id, at=at)
            if metadata is not None:
                context["metadata"] = metadata

            # Guard check
            if defn.guard is not None and not defn.guard(result, context):
                raise TransitionRejected(
                    current=current,
                    transition=transition,
                    required_sources=defn.sources,
                )

            # Action
            if defn.action is not None:
                result = defn.action(result, context)

            # Advance state
            result["current"] = defn.target

            # Record history
            history = list(result.get("history", []))  # type: ignore[arg-type]
            history.append(
                {
                    "source": current,
                    "target": defn.target,
                    "transition": transition,
                    "at": at,
                    "by": actor_id,
                    "metadata": metadata or {},
                }
            )
            result["history"] = history

            logger.info(
                "transition fired: %s → %s (transition=%s, actor=%s)",
                current,
                defn.target,
                transition,
                actor_id,
            )
            return result

        # Case 2: already past the target — idempotent no-op
        current_idx = self._state_index(current)
        target_idx = self._state_index(defn.target)
        if current_idx > target_idx:
            logger.info(
                "transition no-op: current '%s' already past target '%s' (transition=%s)",
                current,
                defn.target,
                transition,
            )
            return result

        # Case 3: not yet at source — reject
        raise TransitionRejected(
            current=current,
            transition=transition,
            required_sources=defn.sources,
        )

    def rewind(self, snapshot: dict[str, StateValue]) -> dict[str, StateValue]:
        """Rewind to the previous state by popping the last history entry."""
        result = copy.deepcopy(snapshot)
        history = list(result.get("history", []))  # type: ignore[arg-type]

        if not history:
            raise RewindRejected(current=str(result.get("current", "")))

        last_entry: dict[str, StateValue] = history.pop()  # type: ignore[assignment]
        source = str(last_entry["source"])
        result["current"] = source
        result["history"] = history

        logger.info(
            "rewind: %s → %s",
            last_entry.get("target"),
            source,
        )
        return result

    def _lookup(self, name: str) -> TransitionDefinition:
        """Find a transition definition by name."""
        for t in self.transitions:
            if t.name == name:
                return t
        raise ValueError(f"unknown transition: '{name}'")

    def _state_index(self, state: str) -> int:
        """Return the index of a state in the ordered states list."""
        try:
            return self.states.index(state)
        except ValueError:
            return -1
