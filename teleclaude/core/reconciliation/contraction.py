"""The fleet's answer to whether a feature-ID may be contracted now."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from teleclaude.core.reconciliation.capability_map import FleetCapabilityMap

#: Answers, for one feature-ID, whether every live computer carries it so a contracting change is safe now.
type ContractionAnswer = Callable[[str], Awaitable[bool]]


def contraction_answer_from_live_map(provider: Callable[[], FleetCapabilityMap | None]) -> ContractionAnswer:
    """The answer over the daemon's live capability map; no map yet is not yet safe."""

    async def answer(feature_id: str) -> bool:
        capability_map = provider()
        return capability_map is not None and capability_map.safe_to_contract(feature_id)

    return answer
