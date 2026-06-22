"""Feature-ID registry for cross-version fleet capability gating."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

FLEET_CROSS_VERSION_INTEROP_FEATURE_ID = "project/spec/feature/reconciliation/fleet-cross-version-interop"
WEBHOOK_INGRESS_FEATURE_ID = "project/spec/feature/integration/single-ingress-webhook-termination"


class FeatureMark(StrEnum):
    """Safety mark for a cross-node feature capability."""

    IGNORABLE = "ignorable"
    MUST_NEGOTIATE = "must_negotiate"


@dataclass(frozen=True)
class FeatureID:
    """One declared feature-ID and its cross-version safety mark."""

    identifier: str
    mark: FeatureMark

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("feature identifier must be non-empty")


@dataclass(frozen=True)
class FeatureIDRegistry:
    """Declared feature-ID catalog plus this node's carried feature set."""

    entries: tuple[FeatureID, ...]
    carried_feature_ids: frozenset[str] | None = None

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for entry in self.entries:
            if entry.identifier in seen:
                raise ValueError(f"duplicate feature identifier: {entry.identifier}")
            seen.add(entry.identifier)

        carried = self.carried_feature_ids
        if carried is None:
            object.__setattr__(self, "carried_feature_ids", frozenset(seen))
            return

        unknown = carried - seen
        if unknown:
            joined = ", ".join(sorted(unknown))
            raise ValueError(f"carried feature identifiers must be declared: {joined}")

    @classmethod
    def from_entries(
        cls,
        entries: Iterable[FeatureID],
        *,
        carried_feature_ids: Iterable[str] | None = None,
    ) -> FeatureIDRegistry:
        """Build a registry from an iterable of entries."""
        carried = None if carried_feature_ids is None else frozenset(carried_feature_ids)
        return cls(tuple(entries), carried)

    def mark_for(self, feature_id: str) -> FeatureMark | None:
        """Return the safety mark for a feature-ID, if this release declares it."""
        for entry in self.entries:
            if entry.identifier == feature_id:
                return entry.mark
        return None

    def carries(self, feature_id: str) -> bool:
        """Return whether this node advertises support for the feature-ID."""
        carried = self.carried_feature_ids
        if carried is None:
            return False
        return feature_id in carried

    def carried_set(self) -> frozenset[str]:
        """Return this node's advertised feature-ID set."""
        carried = self.carried_feature_ids
        if carried is None:
            return frozenset()
        return carried


DEFAULT_FEATURE_ID_REGISTRY = FeatureIDRegistry.from_entries(
    (
        FeatureID(
            identifier=FLEET_CROSS_VERSION_INTEROP_FEATURE_ID,
            mark=FeatureMark.MUST_NEGOTIATE,
        ),
        FeatureID(
            identifier=WEBHOOK_INGRESS_FEATURE_ID,
            mark=FeatureMark.IGNORABLE,
        ),
    )
)


def decode_capability_set(value: object) -> list[str]:
    """Decode a heartbeat capability set into sorted feature-ID strings."""
    if not isinstance(value, list):
        return []
    feature_ids = {item for item in value if isinstance(item, str) and item}
    return sorted(feature_ids)
