"""Fleet capability map materialized from heartbeat advertisements."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FleetCapabilityEntry:
    """One live node's self-advertised capability state."""

    computer: str
    version: str | None
    channel: str | None
    capability_set: frozenset[str]
    last_advertised_at: datetime

    def __post_init__(self) -> None:
        if not self.computer:
            raise ValueError("computer must be non-empty")


@dataclass(frozen=True)
class FleetCapabilityMap:
    """Cluster-wide view of feature-ID support across live nodes."""

    entries: tuple[FleetCapabilityEntry, ...]

    @classmethod
    def materialize(
        cls,
        entries: Iterable[FleetCapabilityEntry],
        *,
        now: datetime,
        heartbeat_ttl_seconds: int,
    ) -> FleetCapabilityMap:
        """Build a capability map, excluding entries whose heartbeat aged out."""
        if heartbeat_ttl_seconds <= 0:
            raise ValueError("heartbeat_ttl_seconds must be positive")

        live_entries = tuple(
            entry for entry in entries if (now - entry.last_advertised_at).total_seconds() <= heartbeat_ttl_seconds
        )
        return cls(tuple(sorted(live_entries, key=lambda entry: entry.computer)))

    def safe_to_require(self, feature_id: str) -> bool:
        """Return whether every live node advertises support for the feature-ID."""
        return self._every_live_node_carries(feature_id)

    def safe_to_contract(self, feature_id: str) -> bool:
        """Return whether every live node advertises support for the feature-ID."""
        return self._every_live_node_carries(feature_id)

    def _every_live_node_carries(self, feature_id: str) -> bool:
        if not feature_id or not self.entries:
            return False
        return all(feature_id in entry.capability_set for entry in self.entries)
