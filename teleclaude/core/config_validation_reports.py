"""Report configuration documents this computer refuses, and their recovery, as platform events.

The daemon judges a changed configuration document with the same validator every load uses.
A refused document is reported once with where it fails, and reported again when a later
version validates, so the alert it raised can close.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.config.errors import ConfigLoadError, load_error_findings
from teleclaude.events.envelope import EventHomeMarker, EventLevel
from teleclaude.events.producer import publish_event
from teleclaude.events.references import ConfigurationRef
from teleclaude.events.schemas.system import (
    ConfigValidationData,
    ConfigValidationFailed,
    ConfigValidationRecovered,
)
from teleclaude.events.wire import LegacyFacts

logger = get_logger(__name__)

# The name the machine configuration's validation is reported under.
MACHINE_CONFIGURATION: Final = "machine"
_REFUSED_EVENT: Final = "config_document_refused"
_RECOVERED_EVENT: Final = "config_document_recovered"
_UNPUBLISHED_EVENT: Final = "config_validation_event_unpublished"
_PRODUCER: Final = "daemon.config_validation"
_DOMAIN: Final = "config"


class ConfigValidationReports:
    """Remember which documents are refused here and report each change of that state once."""

    def __init__(self) -> None:
        self._refused: set[str] = set()

    async def refused(self, configuration: str, document: Path, error: ConfigLoadError) -> None:
        """Report a refused document; repeated refusals of the same document report once."""
        findings = load_error_findings(error)
        logger.error(_REFUSED_EVENT, configuration=configuration, document=str(document), findings=findings)
        if configuration in self._refused:
            return
        self._refused.add(configuration)
        await self._publish(
            ConfigValidationFailed(
                subject=ConfigurationRef(configuration),
                home=EventHomeMarker.NONE,
                data=ConfigValidationData(document=str(document), findings=findings),
            )
        )

    async def accepted(self, configuration: str, document: Path) -> None:
        """Report recovery when a previously refused document now validates."""
        if configuration not in self._refused:
            return
        self._refused.discard(configuration)
        logger.info(_RECOVERED_EVENT, configuration=configuration, document=str(document))
        await self._publish(
            ConfigValidationRecovered(
                subject=ConfigurationRef(configuration),
                home=EventHomeMarker.NONE,
                data=ConfigValidationData(document=str(document), findings=[]),
            )
        )

    async def _publish(self, event: ConfigValidationFailed | ConfigValidationRecovered) -> None:
        try:
            await publish_event(event, LegacyFacts(producer=_PRODUCER, level=EventLevel.OPERATIONAL, domain=_DOMAIN))
        except RuntimeError as error:
            logger.warning(_UNPUBLISHED_EVENT, event=type(event).__name__, error=str(error))
