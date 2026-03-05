"""Trust evaluator cartridge — evaluates event trust and applies outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from instrukt_ai_logging import get_logger

from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext

logger = get_logger(__name__)

_VALID_LEVEL_VALUES: frozenset[int] = frozenset(int(lv) for lv in EventLevel)


@dataclass
class TrustConfig:
    strictness: Literal["permissive", "standard", "strict"] = "standard"
    known_sources: frozenset[str] = field(default_factory=frozenset)


class TrustOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    FLAG = "FLAG"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


class TrustCartridge:
    name = "trust"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        config = context.trust_config
        outcome, flags = self._evaluate(event, config)

        if outcome == TrustOutcome.ACCEPT:
            return event

        if outcome == TrustOutcome.FLAG:
            updated_payload = dict(event.payload)
            updated_payload["_trust_flags"] = flags
            return event.model_copy(update={"payload": updated_payload})

        if outcome == TrustOutcome.QUARANTINE:
            await context.db.quarantine_event(event, flags)
            logger.warning("trust: quarantined event", event=event.event, source=event.source, flags=flags)
            return None

        # REJECT
        logger.warning("trust: rejected event", event=event.event, source=event.source)
        return None

    def _evaluate(self, event: EventEnvelope, config: TrustConfig) -> tuple[TrustOutcome, list[str]]:
        if config.strictness == "permissive":
            return TrustOutcome.ACCEPT, []

        source_known = event.source in config.known_sources

        if config.strictness == "standard":
            if not source_known:
                return TrustOutcome.FLAG, ["unknown_source"]
            if int(event.level) not in _VALID_LEVEL_VALUES:
                return TrustOutcome.QUARANTINE, ["malformed_level"]
            return TrustOutcome.ACCEPT, []

        # strict
        if not source_known:
            return TrustOutcome.QUARANTINE, ["unknown_source"]
        if not event.domain and event.event and not event.event.startswith("system."):
            return TrustOutcome.FLAG, ["missing_domain"]
        if int(event.level) not in _VALID_LEVEL_VALUES:
            return TrustOutcome.REJECT, ["unknown_level"]
        return TrustOutcome.ACCEPT, []
