"""Correlation consumer: detects burst, cascade and entity degradation patterns, and reports when each is over.

Each detection reports once an episode begins (a burst again for every window bucket while it lasts)
and, when the events it counts no longer reach its threshold within the window, reports the episode
over with the ok state of its family. Open episodes are the event catalog's own durable state, so an
episode that began before a restart is still reported over after it. A burst is one event type within
one origin, a failure cascade is the observing computer, and a degradation is one thing (subject and
origin) across all of its failing event types. Correlation acts only on events its own computer
emitted, so each failure is correlated and announced once, by the computer it happened on.

Window rows counted before correlation acted only on its own computer's events are inherited: a count
that decides a detection leaves them out, and a count that decides an episode is over keeps them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.config import config as _global_config
from teleclaude.core.models import HumanActionIntent
from teleclaude.events.catalog import PlatformEvent
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.db import CorrelationEpisode, EpisodeDetection, EventDB
from teleclaude.events.envelope import (
    EventHomeMarker,
    EventLevel,
    EventVisibility,
    ReceivedEvent,
    home_from_token,
    home_token,
    occurrence_id,
)
from teleclaude.events.producer import EventProducer
from teleclaude.events.references import ComputerRef, EventRef, EventTypeRef
from teleclaude.events.schemas.system import (
    BURST_FAMILY,
    ENTITY_FAMILY,
    FAILURE_CASCADE_FAMILY,
    BurstData,
    BurstDetected,
    BurstSubsided,
    BurstSubsidedData,
    EntityDegraded,
    EntityDegradedData,
    EntityRecovered,
    EntityRecoveredData,
    FailureCascadeData,
    FailureCascadeDetected,
    FailureCascadeSubsided,
    FailureCascadeSubsidedData,
)
from teleclaude.events.type_pattern import ANY_TYPE, TypePattern
from teleclaude.events.wire import LegacyFacts

logger = get_logger(__name__)

CORRELATION_CONSUMER = "correlation"

_FAILURE_TYPE_KEYWORDS = ("crash", "fail", "error")
_WORKER_CRASHED_EVENT_TYPE = "teleclaude.system.worker.crashed"
_CORRELATION_PRODUCER = "correlation"
_SYSTEM_DOMAIN = "system"
_BURST_BUCKET_IDENTITY = "burst"
_CASCADE_TIPPED_IDENTITY = "failure_cascade.detected"
_DEGRADATION_TIPPED_IDENTITY = "entity.degraded"
_BURST_ENDED_IDENTITY = "burst.subsided"
_CASCADE_ENDED_IDENTITY = "failure_cascade.subsided"
_DEGRADATION_ENDED_IDENTITY = "entity.recovered"
_CASCADE_ACTION = HumanActionIntent(
    topic="Worker crash cascade",
    summary="Repeated worker crashes were detected.",
    action="Investigate the crashing workers",
)
#: Every state of the families correlation alone emits, so neither its detections nor their ends feed its counts.
_OWN_REPORTS = tuple(TypePattern.below(family) for family in (BURST_FAMILY, FAILURE_CASCADE_FAMILY, ENTITY_FAMILY))

_EPISODE_OPENED_EVENT = "Correlation episode opened"
_EPISODE_OVER_EVENT = "Correlation episode over"


def _is_failure_type(event_type: str) -> bool:
    """Return whether an event type indicates a failure condition."""
    return any(kw in event_type.lower() for kw in _FAILURE_TYPE_KEYWORDS)


@dataclass
class CorrelationConfig:
    """Thresholds and timing controls for correlation heuristics."""

    window_seconds: int = 300
    burst_threshold: int = 10
    crash_cascade_threshold: int = 3
    entity_failure_threshold: int = 3
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def _ended_facts(level: EventLevel) -> LegacyFacts:
    """Legacy facts of an episode-over report: the new ok types carry no notification rule."""
    return LegacyFacts(
        producer=_CORRELATION_PRODUCER,
        level=level,
        domain=_SYSTEM_DOMAIN,
        visibility=EventVisibility.LOCAL,
    )


class _Correlation:
    """Detect correlated operational patterns and emit synthetic system events."""

    def __init__(self, db: EventDB, producer: EventProducer, config: CorrelationConfig) -> None:
        self._db = db
        self._producer = producer
        self._config = config
        # A burst's id is deterministic per computer, type, origin and bucket; this set only spares
        # re-deriving a report already emitted in this run.
        self._emitted_bursts: set[tuple[str, str, int]] = set()

    async def handle(self, event: ReceivedEvent) -> None:
        """Update correlation windows, emit synthetic alerts when thresholds are crossed, and report episodes over."""
        if any(pattern.matches(event.type) for pattern in _OWN_REPORTS):
            return

        config = self._config
        now = config.clock()
        home_key = home_token(event.home)
        subject_key = event.subject.to_token() if event.subject is not None else None
        window_start = now - timedelta(seconds=config.window_seconds)
        prune_before = now - timedelta(seconds=2 * config.window_seconds)

        await self._db.prune_correlation_windows(older_than=prune_before)
        await self._db.increment_correlation_window(event.type, home_key, subject_key, now)

        await self._detect_burst(event, now, window_start)
        await self._detect_failure_cascade(event, now, window_start)
        await self._detect_degradation(event, now, window_start)
        await self._report_ended_episodes(window_start)

    async def _detect_burst(self, event: ReceivedEvent, now: datetime, window_start: datetime) -> None:
        """N events of one type within one origin in the window: report once per window bucket."""
        config = self._config
        home_key = home_token(event.home)
        burst_count = await self._db.get_correlation_count(
            event.type, window_start, include_inherited=False, home=home_key
        )
        if burst_count < config.burst_threshold:
            return
        window_bucket = int(now.timestamp() // config.window_seconds)
        burst_key = (event.type, home_key, window_bucket)
        if burst_key in self._emitted_bursts:
            return
        subject = EventTypeRef(event.type)
        opened = await self._open_episode(EpisodeDetection.BURST, subject.to_ref().to_token(), home_key, now, [])
        emitted = await self._emit(
            BurstDetected(
                id=occurrence_id(
                    _global_config.computer.name, _BURST_BUCKET_IDENTITY, event.type, home_key, str(window_bucket)
                ),
                subject=subject,
                home=event.home,
                data=BurstData(event_type=event.type, window_start=window_start.isoformat(), count=burst_count),
                causationid=event.id,
            ),
            LegacyFacts(
                producer=_CORRELATION_PRODUCER,
                level=EventLevel.OPERATIONAL,
                domain=_SYSTEM_DOMAIN,
                visibility=EventVisibility.LOCAL,
            ),
            opened_episode=(EpisodeDetection.BURST, subject.to_ref().to_token(), home_key) if opened else None,
        )
        if emitted:
            self._emitted_bursts.add(burst_key)

    async def _detect_failure_cascade(self, event: ReceivedEvent, now: datetime, window_start: datetime) -> None:
        """Repeated worker crashes on this computer's event stream: report the cascade."""
        config = self._config
        if event.type != _WORKER_CRASHED_EVENT_TYPE:
            return
        crash_count = await self._db.get_correlation_count(
            _WORKER_CRASHED_EVENT_TYPE, window_start, include_inherited=False
        )
        if crash_count < config.crash_cascade_threshold:
            return
        computer = ComputerRef(_global_config.computer.name)
        cascade_home = home_token(EventHomeMarker.NONE)
        opened = await self._open_episode(
            EpisodeDetection.FAILURE_CASCADE, computer.to_ref().to_token(), cascade_home, now, []
        )
        await self._emit(
            FailureCascadeDetected(
                id=occurrence_id(
                    _global_config.computer.name, _CASCADE_TIPPED_IDENTITY, computer.identity, cascade_home, event.id
                ),
                subject=computer,
                home=EventHomeMarker.NONE,
                data=FailureCascadeData(
                    crash_count=crash_count,
                    window_start=window_start.isoformat(),
                    workers=[],
                ),
                causationid=event.id,
            ),
            LegacyFacts(
                producer=_CORRELATION_PRODUCER,
                level=EventLevel.BUSINESS,
                domain=_SYSTEM_DOMAIN,
                visibility=EventVisibility.CLUSTER,
                human_action=_CASCADE_ACTION,
            ),
            opened_episode=(EpisodeDetection.FAILURE_CASCADE, computer.to_ref().to_token(), cascade_home)
            if opened
            else None,
        )

    async def _detect_degradation(self, event: ReceivedEvent, now: datetime, window_start: datetime) -> None:
        """Repeated failures of one thing within one origin: report the thing degraded, once per episode."""
        config = self._config
        if event.subject is None or not _is_failure_type(event.type):
            return
        home_key = home_token(event.home)
        subject_key = event.subject.to_token()
        fail_count = await self._db.get_correlation_count(
            event.type, window_start, include_inherited=False, home=home_key, subject=subject_key
        )
        if fail_count < config.entity_failure_threshold:
            return
        episode = await self._db.get_episode(EpisodeDetection.ENTITY_DEGRADATION, subject_key, home_key)
        if episode is not None:
            if event.type not in episode.failing_types:
                await self._db.set_episode_failing_types(episode.id, [*episode.failing_types, event.type])
            return
        if not await self._open_episode(EpisodeDetection.ENTITY_DEGRADATION, subject_key, home_key, now, [event.type]):
            return
        await self._emit(
            EntityDegraded(
                id=occurrence_id(
                    _global_config.computer.name, _DEGRADATION_TIPPED_IDENTITY, subject_key, home_key, event.id
                ),
                subject=event.subject,
                home=event.home,
                data=EntityDegradedData(
                    entity=subject_key,
                    failure_count=fail_count,
                    window_start=window_start.isoformat(),
                ),
                causationid=event.id,
            ),
            LegacyFacts(
                producer=_CORRELATION_PRODUCER,
                level=EventLevel.WORKFLOW,
                domain=_SYSTEM_DOMAIN,
                visibility=EventVisibility.LOCAL,
            ),
            opened_episode=(EpisodeDetection.ENTITY_DEGRADATION, subject_key, home_key),
        )

    async def _open_episode(
        self,
        detection: EpisodeDetection,
        subject: str,
        home: str,
        started_at: datetime,
        failing_types: list[str],
    ) -> bool:
        """Open the episode for a detection, subject and origin; log it when it is newly opened."""
        opened = await self._db.open_episode(detection, subject, home, started_at, failing_types)
        if opened:
            logger.info(_EPISODE_OPENED_EVENT, detection=detection.value, subject=subject, home=home)
        return opened

    async def _report_ended_episodes(self, window_start: datetime) -> None:
        """Close and report every open episode whose counted events no longer reach their threshold."""
        for episode in await self._db.list_open_episodes():
            if await self._episode_still_open(episode, window_start):
                continue
            if await self._emit_ended(episode):
                await self._db.close_episode(episode.id)
                logger.info(
                    _EPISODE_OVER_EVENT,
                    detection=episode.detection.value,
                    subject=episode.subject,
                    home=episode.home,
                )

    async def _episode_still_open(self, episode: CorrelationEpisode, window_start: datetime) -> bool:
        """Re-count what the episode's detection counts, inherited window rows included."""
        config = self._config
        if episode.detection is EpisodeDetection.BURST:
            burst_type = EventRef.from_token(episode.subject).identity
            count = await self._db.get_correlation_count(
                burst_type, window_start, include_inherited=True, home=episode.home
            )
            return count >= config.burst_threshold
        if episode.detection is EpisodeDetection.FAILURE_CASCADE:
            count = await self._db.get_correlation_count(
                _WORKER_CRASHED_EVENT_TYPE, window_start, include_inherited=True
            )
            return count >= config.crash_cascade_threshold
        for failing_type in episode.failing_types:
            count = await self._db.get_correlation_count(
                failing_type, window_start, include_inherited=True, home=episode.home, subject=episode.subject
            )
            if count >= config.entity_failure_threshold:
                return True
        return False

    async def _emit_ended(self, episode: CorrelationEpisode) -> bool:
        """Report an episode over with the ok state of its family; the id derives from the episode."""
        computer = _global_config.computer.name
        started = episode.started_at.isoformat()
        home = home_from_token(episode.home)
        if episode.detection is EpisodeDetection.BURST:
            return await self._emit(
                BurstSubsided(
                    id=occurrence_id(computer, _BURST_ENDED_IDENTITY, episode.subject, episode.home, started),
                    subject=EventTypeRef(EventRef.from_token(episode.subject).identity),
                    home=home,
                    data=BurstSubsidedData(episode_start=started),
                ),
                _ended_facts(EventLevel.OPERATIONAL),
            )
        if episode.detection is EpisodeDetection.FAILURE_CASCADE:
            return await self._emit(
                FailureCascadeSubsided(
                    id=occurrence_id(computer, _CASCADE_ENDED_IDENTITY, episode.subject, episode.home, started),
                    subject=ComputerRef(EventRef.from_token(episode.subject).identity),
                    home=EventHomeMarker.NONE,
                    data=FailureCascadeSubsidedData(episode_start=started),
                ),
                _ended_facts(EventLevel.BUSINESS),
            )
        return await self._emit(
            EntityRecovered(
                id=occurrence_id(computer, _DEGRADATION_ENDED_IDENTITY, episode.subject, episode.home, started),
                subject=EventRef.from_token(episode.subject),
                home=home,
                data=EntityRecoveredData(episode_start=started),
            ),
            _ended_facts(EventLevel.WORKFLOW),
        )

    async def _emit(
        self,
        event: PlatformEvent[Any, Any],
        legacy: LegacyFacts,
        opened_episode: tuple[EpisodeDetection, str, str] | None = None,
    ) -> bool:
        """Emit a synthetic correlation event through the producer.

        An episode opened for this report is closed again when the report is not delivered, so a
        replay of the triggering event opens it and reports it again instead of finding it open.
        """
        try:
            await self._producer.emit(event, legacy)
        except Exception:
            await self._abandon_episode(opened_episode)
            raise
        return True

    async def _abandon_episode(self, episode_key: tuple[EpisodeDetection, str, str] | None) -> None:
        """Close an episode whose opening report was not delivered."""
        if episode_key is None:
            return
        episode = await self._db.get_episode(*episode_key)
        if episode is not None:
            await self._db.close_episode(episode.id)


def build_correlation_consumer(db: EventDB, producer: EventProducer, config: CorrelationConfig) -> Consumer:
    """The consumer that correlates this computer's events into burst, cascade and degradation reports."""
    correlation = _Correlation(db, producer, config)
    return Consumer(
        name=CORRELATION_CONSUMER,
        interest=Interest(types=(ANY_TYPE,), own_computer_only=True),
        handler=correlation.handle,
    )
