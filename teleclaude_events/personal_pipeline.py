"""Personal subscription pipeline — per-member leaf cartridges."""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude_events.cartridge_loader import LoadedCartridge, discover_cartridges
from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.pipeline import PipelineContext

logger = get_logger(__name__)


class PersonalPipeline:
    def __init__(self, member_id: str, cartridges: list[LoadedCartridge]) -> None:
        self.member_id = member_id
        self.cartridges = cartridges

    async def run(self, event: EventEnvelope, context: PipelineContext) -> None:
        for cartridge in self.cartridges:
            try:
                await cartridge.process(event, context)
            except Exception as e:
                logger.error(
                    "Personal cartridge '%s' for member '%s' raised an exception: %s",
                    cartridge.manifest.id,
                    self.member_id,
                    e,
                    exc_info=True,
                )


def load_personal_pipeline(member_id: str, path: Path) -> PersonalPipeline:
    """Discover and load personal cartridges for a member."""
    all_cartridges = discover_cartridges(path)
    valid: list[LoadedCartridge] = []

    for c in all_cartridges:
        if not c.manifest.personal:
            logger.warning(
                "Personal cartridge '%s' for member '%s' has personal=False — rejected",
                c.manifest.id,
                member_id,
            )
            continue
        if c.manifest.depends_on:
            logger.warning(
                "Personal cartridge '%s' for member '%s' declares depends_on — rejected (leaf node required)",
                c.manifest.id,
                member_id,
            )
            continue
        valid.append(c)

    return PersonalPipeline(member_id=member_id, cartridges=valid)
