"""What the running daemon reports about the configuration versions its migrations reach."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReachState(StrEnum):
    """How the running daemon answered the question of which configuration versions it can read."""

    NOT_LISTENING = "not_listening"
    REPORTED = "reported"
    NOT_REPORTED = "not_reported"
    UNANSWERED = "unanswered"


_REACH_CONTRACT = "A reported reach is exactly the reach of a state that reports one"
_NOT_LISTENING_DIAGNOSTIC = "no daemon listens; the current version is {current}"
_REPORTED_DIAGNOSTIC = "the running daemon reports migration reach {reach}; the current version is {current}"
_NOT_REPORTED_DIAGNOSTIC = "the running daemon reports no migration reach; the current version is {current}"
_UNANSWERED_DIAGNOSTIC = "the listening daemon did not answer with a migration reach within its bounded wait; the current version is {current}"
_DIAGNOSTICS: dict[ReachState, str] = {
    ReachState.NOT_LISTENING: _NOT_LISTENING_DIAGNOSTIC,
    ReachState.REPORTED: _REPORTED_DIAGNOSTIC,
    ReachState.NOT_REPORTED: _NOT_REPORTED_DIAGNOSTIC,
    ReachState.UNANSWERED: _UNANSWERED_DIAGNOSTIC,
}


@dataclass(frozen=True)
class DaemonReach:
    """The running daemon's answer, as the migration run needs it to decide whether it may store documents."""

    state: ReachState
    reach: int | None = None

    def __post_init__(self) -> None:
        if (self.state is ReachState.REPORTED) != (self.reach is not None):
            raise ValueError(_REACH_CONTRACT)

    def withholds(self, current_version: int) -> bool:
        """Whether storing documents at the current version could outrun what the running daemon reads.

        Only a daemon that reports a reach at or above the current version, or the absence of any daemon,
        lets a run store; a daemon that reports nothing, or does not answer, is not known to read it.
        """
        if self.state is ReachState.NOT_LISTENING:
            return False
        if self.reach is None:
            return True
        return self.reach < current_version

    def describe(self, current_version: int) -> str:
        """Name the daemon's reach, or why it is unknown, beside the current version."""
        return _DIAGNOSTICS[self.state].format(reach=self.reach, current=current_version)
