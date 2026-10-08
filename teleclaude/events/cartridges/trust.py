"""Trust evaluator cartridge — evaluates event trust and applies outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, cast

from instrukt_ai_logging import get_logger
from pydantic import JsonValue

from teleclaude.events.envelope import EventLevel
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.wire import StreamEvent

logger = get_logger(__name__)

_VALID_LEVEL_VALUES: frozenset[int] = frozenset(int(lv) for lv in EventLevel)
_SYSTEM_TYPE_PREFIX = "teleclaude.system."


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

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    async def process(self, event: StreamEvent, context: PipelineContext) -> StreamEvent | None:
        """Apply trust evaluation and return the resulting event disposition."""
        config = context.trust_config
        outcome, flags = self._evaluate(event, config)

        if outcome == TrustOutcome.ACCEPT:
            return event

        if outcome == TrustOutcome.FLAG:
            updated_data = dict(event.data)
            updated_data["_trust_flags"] = cast(JsonValue, flags)
            return event.model_copy(update={"data": updated_data})

        if outcome == TrustOutcome.QUARANTINE:
            await context.db.quarantine_event(event, flags)
            logger.warning("trust: quarantined event", event=event.type, source=event.legacy.producer, flags=flags)
            return None

        # REJECT
        logger.warning("trust: rejected event", event=event.type, source=event.legacy.producer)
        return None

    def _evaluate(self, event: StreamEvent, config: TrustConfig) -> tuple[TrustOutcome, list[str]]:
        """Evaluate an event against the configured trust policy."""
        outcome = TrustOutcome.ACCEPT
        flags: list[str] = []

        if config.strictness == "permissive":
            return outcome, flags

        source_known = event.legacy.producer in config.known_sources

        if config.strictness == "standard":
            if not source_known:
                outcome, flags = TrustOutcome.FLAG, ["unknown_source"]
            elif int(event.legacy.level) not in _VALID_LEVEL_VALUES:
                outcome, flags = TrustOutcome.QUARANTINE, ["malformed_level"]
            return outcome, flags

        if not source_known:
            outcome, flags = TrustOutcome.QUARANTINE, ["unknown_source"]
        elif not event.legacy.domain and event.type and not event.type.startswith(_SYSTEM_TYPE_PREFIX):
            outcome, flags = TrustOutcome.FLAG, ["missing_domain"]
        elif int(event.legacy.level) not in _VALID_LEVEL_VALUES:
            outcome, flags = TrustOutcome.REJECT, ["unknown_level"]
        return outcome, flags

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name
