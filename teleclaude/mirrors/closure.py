"""Closure readiness: a session ending requests its mirror's coverage, and coverage is reported as an event.

Closing a session asks the same refresh capability that agent-stop and reconciliation use to confirm the
conversation mirror covers the closed conversation, and reports the result as a published fact. Other contexts
learn coverage from that event, never from mirror storage.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from instrukt_ai_logging import get_logger

from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import EventLevel, ReceivedEvent, occurrence_id
from teleclaude.events.envelope_facts import home_for_session_config
from teleclaude.events.producer import publish_event
from teleclaude.events.references import SessionRef
from teleclaude.events.renames import RETIRED_SESSION_ENDED_TYPE
from teleclaude.events.schemas.session_mirrors import MirrorCovered, MirrorCoveredData
from teleclaude.events.schemas.system import SESSION_ENDED_PREFIX, SessionEndedData
from teleclaude.events.type_pattern import TypePattern
from teleclaude.events.wire import LegacyFacts

from .conversations import reset_coverage_readiness
from .generator import MirrorCoverage, MirrorWriteTrigger, refresh_session_mirror

logger = get_logger(__name__)

type CoverageReporter = Callable[[MirrorCoverage], None]
"""Reports a session mirror's coverage as a published fact; blocks until the report is made."""

MIRROR_CLOSURE_CONSUMER = "mirror-closure"
_PUBLISH_TIMEOUT_S = 30.0
_PRODUCER = "session_mirrors"
_COVERAGE_PUBLISHED_EVENT = "mirror.coverage_published"
_COVERAGE_PUBLISH_FAILED_EVENT = "mirror.coverage_publish_failed"
_SESSION_MISSING_EVENT = "mirror.closure_session_missing"
_SESSION_ENDED_PATTERNS = (TypePattern.below(SESSION_ENDED_PREFIX), TypePattern(RETIRED_SESSION_ENDED_TYPE))


def coverage_is_news(coverage: MirrorCoverage, trigger: MirrorWriteTrigger) -> bool:
    """Whether a refresh reached coverage other contexts have not been told.

    A closure always reports, ready or not. Any other refresh reports when it makes a mirror ready that was
    not, so a closure that waited on an unreadable source is released by the refresh that reads it.
    """
    return trigger is MirrorWriteTrigger.CLOSURE or (coverage.ready and not coverage.previously_ready)


async def publish_mirror_covered(coverage: MirrorCoverage) -> None:
    """Publish a session mirror's coverage; a failed publication leaves the mirror unready so a later refresh reports it."""
    try:
        await publish_event(
            MirrorCovered(
                id=occurrence_id(coverage.session_id, coverage.covered_at),
                subject=SessionRef(coverage.session_id),
                home=home_for_session_config(coverage.config_subject),
                data=MirrorCoveredData(
                    session_id=coverage.session_id,
                    covered_at=coverage.covered_at,
                    ready=coverage.ready,
                    complete=coverage.complete,
                    missing_source_count=len(coverage.missing_sources),
                    message_count=coverage.message_count,
                ),
            ),
            LegacyFacts(producer=_PRODUCER, level=EventLevel.OPERATIONAL, domain=_PRODUCER),
        )
    except Exception as exc:
        reset_coverage_readiness(coverage.session_id)
        logger.error(_COVERAGE_PUBLISH_FAILED_EVENT, session_id=coverage.session_id, error=str(exc), exc_info=True)
        raise
    logger.info(
        _COVERAGE_PUBLISHED_EVENT,
        session_id=coverage.session_id,
        ready=coverage.ready,
        complete=coverage.complete,
        missing_sources=len(coverage.missing_sources),
    )


async def refresh_and_report_coverage(session_id: str, trigger: MirrorWriteTrigger) -> MirrorCoverage | None:
    """Refresh a session's mirror and report its coverage when that is news; ``None`` when no session record exists."""
    coverage = await refresh_session_mirror(session_id, db=None, trigger=trigger)
    if coverage is None:
        logger.info(_SESSION_MISSING_EVENT, session_id=session_id)
        return None
    if coverage_is_news(coverage, trigger):
        await publish_mirror_covered(coverage)
    return coverage


async def _on_session_ended(event: ReceivedEvent) -> None:
    """Request the ended session's mirror coverage; a failure raises so the platform hands the ending again."""
    ended = SessionEndedData.model_validate(event.data)
    await refresh_and_report_coverage(ended.session_id, MirrorWriteTrigger.CLOSURE)


def build_mirror_closure_consumer() -> Consumer:
    """The consumer that confirms mirror coverage for every session ending on this computer."""
    return Consumer(
        name=MIRROR_CLOSURE_CONSUMER,
        interest=Interest(types=_SESSION_ENDED_PATTERNS, own_computer_only=True),
        handler=_on_session_ended,
    )


def threadsafe_coverage_reporter(loop: asyncio.AbstractEventLoop) -> CoverageReporter:
    """A reporter for the mirror worker's thread that publishes on the daemon's event loop."""

    def report(coverage: MirrorCoverage) -> None:
        asyncio.run_coroutine_threadsafe(publish_mirror_covered(coverage), loop).result(timeout=_PUBLISH_TIMEOUT_S)

    return report
