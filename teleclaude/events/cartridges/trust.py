"""Trust evaluator cartridge — evaluates event trust and applies outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)

_VALID_LEVEL_VALUES: frozenset[int] = frozenset(int(lv) for lv in EventLevel)


@dataclass
class TrustConfig:
    """Trust evaluation thresholds and source allow-list configuration."""

    strictness: Literal["permissive", "standard", "strict"] = "standard"
    known_sources: frozenset[str] = field(default_factory=frozenset)


class TrustOutcome(str, Enum):
    """Possible outcomes of trust evaluation."""

    ACCEPT = "ACCEPT"
    FLAG = "FLAG"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


class TrustCartridge:
    """Evaluate trustworthiness and quarantine or annotate events as needed."""

    name = "trust"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        """Apply trust evaluation and return the resulting event disposition."""
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
        """Evaluate an event against the configured trust policy."""
        outcome = TrustOutcome.ACCEPT
        flags: list[str] = []

        if config.strictness == "permissive":
            return outcome, flags

        source_known = event.source in config.known_sources

        if config.strictness == "standard":
            if not source_known:
                outcome, flags = TrustOutcome.FLAG, ["unknown_source"]
            elif int(event.level) not in _VALID_LEVEL_VALUES:
                outcome, flags = TrustOutcome.QUARANTINE, ["malformed_level"]
            return outcome, flags

        if not source_known:
            outcome, flags = TrustOutcome.QUARANTINE, ["unknown_source"]
        elif not event.domain and event.event and not event.event.startswith("system."):
            outcome, flags = TrustOutcome.FLAG, ["missing_domain"]
        elif int(event.level) not in _VALID_LEVEL_VALUES:
            outcome, flags = TrustOutcome.REJECT, ["unknown_level"]
        return outcome, flags

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name
