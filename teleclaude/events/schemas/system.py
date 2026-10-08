"""Platform event declarations: sessions, configuration, the daemon, processes, and the event platform's own detections."""

from __future__ import annotations

from teleclaude.events.catalog import DeclaredEvent, EventData, LifecycleState, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import (
    ComputerRef,
    ConfigurationRef,
    EventRef,
    EventTypeRef,
    SessionRef,
    StreamEntryRef,
)

_SESSION_HOMES = (EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY)
_PROJECT_HOME = (EventHomeKind.PROJECT,)

BURST_FAMILY = "teleclaude.system.burst"
FAILURE_CASCADE_FAMILY = "teleclaude.system.failure_cascade"
ENTITY_FAMILY = "teleclaude.system.entity"


class SessionEndedData(EventData):
    ended_at: str
    project_path: str
    session_id: str


class SessionRestartFailedData(EventData):
    computer: str
    phase: str
    reason: str
    restart_group: str
    session_id: str


class SessionBootstrapFailedData(EventData):
    project_path: str | None = None
    reason: str
    session_id: str


class EffectiveConfigUpdatedData(EventData):
    changed_sections: list[str]
    project_path: str
    updated_at: str


class DaemonRestartedData(EventData):
    computer: str
    pid: int


class ProcessReapedData(EventData):
    lease_expires_at: str | None = None
    observe_only: bool
    owner: str | None = None
    pid: int
    reason: str
    signature_id: str
    signature_name: str


class NoData(EventData):
    """An event whose type and subject state everything it has to say."""


class DeadLetteredData(EventData):
    attempt_count: str
    consumer: str
    consumer_id: str
    dlq_destination: str
    failing_stage: str
    original_entry_id: str
    original_stream: str


class BurstData(EventData):
    count: int
    event_type: str
    window_start: str


class BurstSubsidedData(EventData):
    episode_start: str


class FailureCascadeData(EventData):
    crash_count: int
    window_start: str
    workers: list[str]


class FailureCascadeSubsidedData(EventData):
    episode_start: str


class EntityDegradedData(EventData):
    entity: str
    failure_count: int
    window_start: str


class EntityRecoveredData(EventData):
    episode_start: str


class SessionEnded(PlatformEvent[SessionRef, SessionEndedData]):
    NAME = "teleclaude.agent_runtime.session.ended"
    DESCRIPTION = "A session was closed and may require lifecycle-runner re-evaluation of its todo"
    HOME_KINDS = _SESSION_HOMES


class SessionRestartFailed(PlatformEvent[SessionRef, SessionRestartFailedData]):
    NAME = "teleclaude.agent_runtime.session.restart_failed"
    DESCRIPTION = "An agent restart failed before the agent could resume, and the session was kept alive for inspection"
    HOME_KINDS = _SESSION_HOMES


class SessionBootstrapFailed(PlatformEvent[SessionRef, SessionBootstrapFailedData]):
    NAME = "teleclaude.system.session.bootstrap_failed"
    DESCRIPTION = "A session's tmux/identity bootstrap failed, stranding it before it reached active"
    HOME_KINDS = _SESSION_HOMES


class EffectiveConfigUpdated(PlatformEvent[ConfigurationRef, EffectiveConfigUpdatedData]):
    NAME = "teleclaude.config.effective.updated"
    DESCRIPTION = "Effective project configuration changed and may affect workflow runner eligibility"
    HOME_KINDS = _PROJECT_HOME


class DaemonRestarted(PlatformEvent[ComputerRef, DaemonRestartedData]):
    NAME = "teleclaude.system.daemon.restarted"
    DESCRIPTION = "Daemon process restarted on a computer"


class ProcessReaped(PlatformEvent[ComputerRef, ProcessReapedData]):
    NAME = "teleclaude.system.process.reaped"
    DESCRIPTION = "Process janitor reaped or observed a reapable process"


class WorkerCrashed(PlatformEvent[ComputerRef, NoData]):
    NAME = "teleclaude.system.worker.crashed"
    DESCRIPTION = "A background worker crashed unexpectedly"


class EventDeadLettered(PlatformEvent[StreamEntryRef, DeadLetteredData]):
    NAME = "teleclaude.system.event.dead_lettered"
    DESCRIPTION = "An event exhausted its retry ceiling and transitioned to the dead-letter destination"


class BurstDetected(PlatformEvent[EventTypeRef, BurstData]):
    FAMILY = BURST_FAMILY
    STATE = LifecycleState.DETECTED
    DESCRIPTION = "A burst of events of the same type was detected within a short window"
    HOME_KINDS = _SESSION_HOMES


class BurstSubsided(PlatformEvent[EventTypeRef, BurstSubsidedData]):
    FAMILY = BURST_FAMILY
    STATE = LifecycleState.SUBSIDED
    DESCRIPTION = "Events of a type that burst no longer reach the burst threshold within the detection window"
    HOME_KINDS = _SESSION_HOMES


class FailureCascadeDetected(PlatformEvent[ComputerRef, FailureCascadeData]):
    FAMILY = FAILURE_CASCADE_FAMILY
    STATE = LifecycleState.DETECTED
    DESCRIPTION = "Multiple worker crashes detected within a short window"


class FailureCascadeSubsided(PlatformEvent[ComputerRef, FailureCascadeSubsidedData]):
    FAMILY = FAILURE_CASCADE_FAMILY
    STATE = LifecycleState.SUBSIDED
    DESCRIPTION = "Worker crashes no longer reach the failure-cascade threshold within the detection window"


class EntityDegraded(PlatformEvent[EventRef, EntityDegradedData]):
    FAMILY = ENTITY_FAMILY
    STATE = LifecycleState.DEGRADED
    DESCRIPTION = "Repeated failures detected for the same thing within a short window"
    HOME_KINDS = _SESSION_HOMES


class EntityRecovered(PlatformEvent[EventRef, EntityRecoveredData]):
    FAMILY = ENTITY_FAMILY
    STATE = LifecycleState.RECOVERED
    DESCRIPTION = "None of a degraded thing's failing event types reaches the degradation threshold any more"
    HOME_KINDS = _SESSION_HOMES


DECLARED: tuple[DeclaredEvent, ...] = (
    SessionEnded,
    SessionRestartFailed,
    SessionBootstrapFailed,
    EffectiveConfigUpdated,
    DaemonRestarted,
    ProcessReaped,
    WorkerCrashed,
    EventDeadLettered,
    BurstDetected,
    BurstSubsided,
    FailureCascadeDetected,
    FailureCascadeSubsided,
    EntityDegraded,
    EntityRecovered,
)
