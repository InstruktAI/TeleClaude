"""Fleet coverage decisions for history searches."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from teleclaude.constants import ComputerStatus


class FleetComputer(Protocol):
    """Presence facts needed to select history search targets."""

    @property
    def name(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def is_local(self) -> bool: ...


@dataclass(frozen=True)
class FleetSelection:
    """Targets, excluded computers, and whether fleet coverage is incomplete."""

    targets: tuple[str, ...]
    skipped: tuple[str, ...]
    incomplete: bool


def select_history_fleet(local: str, roster: Sequence[FleetComputer] | None) -> FleetSelection:
    """Select online peers, retaining local coverage when the roster is unavailable."""
    if roster is None:
        return FleetSelection(targets=(local,), skipped=(), incomplete=True)
    return FleetSelection(
        targets=(
            local,
            *(entry.name for entry in roster if not entry.is_local and entry.status == ComputerStatus.ONLINE),
        ),
        skipped=tuple(entry.name for entry in roster if not entry.is_local and entry.status != ComputerStatus.ONLINE),
        incomplete=False,
    )
