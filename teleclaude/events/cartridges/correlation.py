"""Correlation cartridge — detects burst, cascade and entity degradation patterns, and reports when each is over.

Each detection reports once an episode begins (a burst again for every window bucket
while it lasts) and, when the events it counts no longer reach its threshold within the
window, reports the episode over with the ok state of its family. Open episodes are the
event catalog's own durable state, so an episode that began before a restart is still
reported over after it. A burst is one event type within one home, a failure cascade is
the observing computer, and a degradation is one thing (subject and home) across all of
its failing event types.
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
from teleclaude.events.db import CorrelationEpisode, EpisodeDetection
from teleclaude.events.envelope import (
    EventHomeMarker,
    EventLevel,
    EventVisibility,
    home_from_token,
    home_token,
    occurrence_id,
)
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.references import ComputerRef, EventRef, EventTypeRef
from teleclaude.events.schemas.system import (
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
from teleclaude.events.wire import LegacyFacts, StreamEvent

logger = get_logger(__name__)

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


class CorrelationCartridge:
    """Detect correlated operational patterns and emit synthetic system events."""

    name = "correlation"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    def __init__(self) -> None:
        # Burst identity is deterministic per host, type, home and bucket; durable
        # pipeline idempotency suppresses replays across restarts.
        self._emitted_bursts: set[tuple[str, str, int]] = set()

    async def process(self, event: StreamEvent, context: PipelineContext) -> StreamEvent | None:
        """Update correlation windows, emit synthetic alerts when thresholds are crossed, and report episodes over."""
        # Skip synthetic events from correlation to prevent re-entry loops
        if event.legacy.producer == _CORRELATION_PRODUCER:
            return event

        config = context.correlation_config
        now = config.clock()
        home_key = home_token(event.home)
        subject_key = event.subject.to_token() if event.subject is not None else None
        window_start = now - timedelta(seconds=config.window_seconds)
        prune_before = now - timedelta(seconds=2 * config.window_seconds)

        await context.db.prune_correlation_windows(older_than=prune_before)
        await context.db.increment_correlation_window(event.type, home_key, subject_key, now)

        await self._detect_burst(event, context, now, window_start)
        await self._detect_failure_cascade(event, context, now, window_start)
        await self._detect_degradation(event, context, now, window_start)
        await self._report_ended_episodes(context, window_start)
        return event

    async def _detect_burst(
        self, event: StreamEvent, context: PipelineContext, now: datetime, window_start: datetime
    ) -> None:
        """N events of one type within one home in the window: report once per window bucket."""
        config = context.correlation_config
        home_key = home_token(event.home)
        burst_count = await context.db.get_correlation_count(event.type, window_start, home=home_key)
        if burst_count < config.burst_threshold:
            return
        window_bucket = int(now.timestamp() // config.window_seconds)
        burst_key = (event.type, home_key, window_bucket)
        if burst_key in self._emitted_bursts:
            return
        subject = EventTypeRef(event.type)
        opened = await self._open_episode(
            context, EpisodeDetection.BURST, subject.to_ref().to_token(), home_key, now, []
        )
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
            context,
            opened_episode=(EpisodeDetection.BURST, subject.to_ref().to_token(), home_key) if opened else None,
        )
        if emitted:
            self._emitted_bursts.add(burst_key)

    async def _detect_failure_cascade(
        self, event: StreamEvent, context: PipelineContext, now: datetime, window_start: datetime
    ) -> None:
        """Repeated worker crashes on this computer's event stream: report the cascade."""
        config = context.correlation_config
        if event.type != _WORKER_CRASHED_EVENT_TYPE:
            return
        crash_count = await context.db.get_correlation_count(_WORKER_CRASHED_EVENT_TYPE, window_start)
        if crash_count < config.crash_cascade_threshold:
            return
        computer = ComputerRef(_global_config.computer.name)
        cascade_home = home_token(EventHomeMarker.NONE)
        opened = await self._open_episode(
            context, EpisodeDetection.FAILURE_CASCADE, computer.to_ref().to_token(), cascade_home, now, []
        )
        entity = event.legacy.entity
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
                    workers=[entity] if entity else [],
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
            context,
            opened_episode=(EpisodeDetection.FAILURE_CASCADE, computer.to_ref().to_token(), cascade_home)
            if opened
            else None,
        )

    async def _detect_degradation(
        self, event: StreamEvent, context: PipelineContext, now: datetime, window_start: datetime
    ) -> None:
        """Repeated failures of one thing within one home: report the thing degraded, once per episode."""
        config = context.correlation_config
        if event.subject is None or not _is_failure_type(event.type):
            return
        home_key = home_token(event.home)
        subject_key = event.subject.to_token()
        fail_count = await context.db.get_correlation_count(
            event.type, window_start, home=home_key, subject=subject_key
        )
        if fail_count < config.entity_failure_threshold:
            return
        episode = await context.db.get_episode(EpisodeDetection.ENTITY_DEGRADATION, subject_key, home_key)
        if episode is not None:
            if event.type not in episode.failing_types:
                await context.db.set_episode_failing_types(episode.id, [*episode.failing_types, event.type])
            return
        if not await self._open_episode(
            context, EpisodeDetection.ENTITY_DEGRADATION, subject_key, home_key, now, [event.type]
        ):
            return
        await self._emit(
            EntityDegraded(
                id=occurrence_id(
                    _global_config.computer.name, _DEGRADATION_TIPPED_IDENTITY, subject_key, home_key, event.id
                ),
                subject=event.subject,
                home=event.home,
                data=EntityDegradedData(
                    entity=event.legacy.entity or subject_key,
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
            context,
            opened_episode=(EpisodeDetection.ENTITY_DEGRADATION, subject_key, home_key),
        )

    async def _open_episode(
        self,
        context: PipelineContext,
        detection: EpisodeDetection,
        subject: str,
        home: str,
        started_at: datetime,
        failing_types: list[str],
    ) -> bool:
        """Open the episode for a detection, subject and home; log it when it is newly opened."""
        opened = await context.db.open_episode(detection, subject, home, started_at, failing_types)
        if opened:
            logger.info("correlation: episode opened", detection=detection.value, subject=subject, home=home)
        return opened

    async def _report_ended_episodes(self, context: PipelineContext, window_start: datetime) -> None:
        """Close and report every open episode whose counted events no longer reach their threshold."""
        for episode in await context.db.list_open_episodes():
            if await self._episode_still_open(episode, context, window_start):
                continue
            if await self._emit_ended(episode, context):
                await context.db.close_episode(episode.id)
                logger.info(
                    "correlation: episode over",
                    detection=episode.detection.value,
                    subject=episode.subject,
                    home=episode.home,
                )

    async def _episode_still_open(
        self, episode: CorrelationEpisode, context: PipelineContext, window_start: datetime
    ) -> bool:
        """Re-count what the episode's detection counts, with the existing window counts."""
        config = context.correlation_config
        if episode.detection is EpisodeDetection.BURST:
            burst_type = EventRef.from_token(episode.subject).identity
            count = await context.db.get_correlation_count(burst_type, window_start, home=episode.home)
            return count >= config.burst_threshold
        if episode.detection is EpisodeDetection.FAILURE_CASCADE:
            count = await context.db.get_correlation_count(_WORKER_CRASHED_EVENT_TYPE, window_start)
            return count >= config.crash_cascade_threshold
        for failing_type in episode.failing_types:
            count = await context.db.get_correlation_count(
                failing_type, window_start, home=episode.home, subject=episode.subject
            )
            if count >= config.entity_failure_threshold:
                return True
        return False

    async def _emit_ended(self, episode: CorrelationEpisode, context: PipelineContext) -> bool:
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
                context,
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
                context,
            )
        return await self._emit(
            EntityRecovered(
                id=occurrence_id(computer, _DEGRADATION_ENDED_IDENTITY, episode.subject, episode.home, started),
                subject=EventRef.from_token(episode.subject),
                home=home,
                data=EntityRecoveredData(episode_start=started),
            ),
            _ended_facts(EventLevel.WORKFLOW),
            context,
        )

    async def _emit(
        self,
        event: PlatformEvent[Any, Any],
        legacy: LegacyFacts,
        context: PipelineContext,
        opened_episode: tuple[EpisodeDetection, str, str] | None = None,
    ) -> bool:
        """Emit a synthetic correlation event through the configured producer.

        An episode opened for this report is closed again when the report is not delivered, so a
        replay of the triggering event opens it and reports it again instead of finding it open.
        """
        if context.producer is None:
            logger.warning(
                "correlation: no producer configured, cannot emit synthetic event",
                event_type=event.type_name(),
            )
            await self._abandon_episode(context, opened_episode)
            return False
        try:
            await context.producer.emit(event, legacy)
        except Exception:
            await self._abandon_episode(context, opened_episode)
            raise
        return True

    async def _abandon_episode(
        self, context: PipelineContext, episode_key: tuple[EpisodeDetection, str, str] | None
    ) -> None:
        """Close an episode whose opening report was not delivered."""
        if episode_key is None:
            return
        episode = await context.db.get_episode(*episode_key)
        if episode is not None:
            await context.db.close_episode(episode.id)

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name
