"""Platform event declarations: sessions, configuration, the daemon, processes, and the event platform's own detections."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue

from teleclaude.core.agent_availability import AgentAvailabilityStatus
from teleclaude.core.events import AgentHookEventType
from teleclaude.events.catalog import DeclaredEvent, EventData, LifecycleState, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import (
    ComputerRef,
    ConfigurationRef,
    EventRef,
    EventTypeRef,
    OperationRef,
    SessionRef,
    StreamEntryRef,
)
from teleclaude.events.renames import RETIRED_SESSION_ENDED_TYPE

_SESSION_HOMES = (EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY)
_PROJECT_HOME = (EventHomeKind.PROJECT,)

BURST_FAMILY = "teleclaude.system.burst"
FAILURE_CASCADE_FAMILY = "teleclaude.system.failure_cascade"
ENTITY_FAMILY = "teleclaude.system.entity"
CONFIG_VALIDATION_FAMILY = "teleclaude.config.validation"
_RUNTIME_OPERATION_OUTCOME_FAMILY = "teleclaude.agent_runtime.operation"
_RUNTIME_OPERATION_HOME_KINDS = (EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY)
#: The name every kinded session-ended type sits below; a subscriber selects one kind or every ending through it.
SESSION_ENDED_PREFIX = RETIRED_SESSION_ENDED_TYPE


class SessionEndedKind(StrEnum):
    """The kinds of session an ending is reported for, each the last segment of its type name."""

    HELP_DESK = "help_desk"
    PERSON = "person"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class RuntimeSessionChange(StrEnum):
    """Source-row changes that request current session reconciliation."""

    CREATED = "created"
    UPDATED = "updated"
    CLOSED = "closed"


class RuntimeOperationResult(StrEnum):
    """Terminal result carried by a durable operation occurrence."""

    COMPLETED = "completed"
    FAILED = "failed"


class SessionEndedData(EventData):
    ended_at: str
    project_path: str | None = None
    session_id: str


class RuntimeSessionSourceChangedData(EventData):
    session_id: str
    change: RuntimeSessionChange
    changed_fields: list[str] = Field(default_factory=list)


class RuntimeSessionStatusData(EventData):
    session_id: str
    status: str
    reason: str
    timestamp: str
    last_activity_at: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None


class RuntimeAgentActivityData(EventData):
    session_id: str
    event_type: AgentHookEventType
    timestamp: str | None = None
    canonical_type: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class RuntimeAgentAvailabilityData(EventData):
    agent: str
    status: AgentAvailabilityStatus | None = None
    status_until: str | None = None
    reason: str | None = None
    error: str | None = None
    model: str | None = None
    model_status: AgentAvailabilityStatus | None = None
    model_status_until: str | None = None
    model_reason: str | None = None


class RuntimeErrorData(EventData):
    session_id: str | None
    message: str
    source: str | None = None
    details: dict[str, JsonValue] | None = None
    severity: str
    retryable: bool
    code: str | None = None


class RuntimeOperationOutcomeData(EventData):
    operation_id: str
    operation_kind: str
    error: str | None = None


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


class ConfigValidationData(EventData):
    """One configuration document and where it fails; findings carry locations and messages, never values."""

    document: str
    findings: list[str]


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


class HelpDeskSessionEnded(PlatformEvent[SessionRef, SessionEndedData]):
    NAME = f"{SESSION_ENDED_PREFIX}.{SessionEndedKind.HELP_DESK.value}"
    DESCRIPTION = "A help-desk conversation session ended"
    HOME_KINDS = _SESSION_HOMES


class PersonSessionEnded(PlatformEvent[SessionRef, SessionEndedData]):
    NAME = f"{SESSION_ENDED_PREFIX}.{SessionEndedKind.PERSON.value}"
    DESCRIPTION = "A session a person started and talks to ended"
    HOME_KINDS = _SESSION_HOMES


class SystemSessionEnded(PlatformEvent[SessionRef, SessionEndedData]):
    NAME = f"{SESSION_ENDED_PREFIX}.{SessionEndedKind.SYSTEM.value}"
    DESCRIPTION = "A session the system started ended"
    HOME_KINDS = _SESSION_HOMES


class UnknownSessionEnded(PlatformEvent[SessionRef, SessionEndedData]):
    NAME = f"{SESSION_ENDED_PREFIX}.{SessionEndedKind.UNKNOWN.value}"
    DESCRIPTION = "A session ended whose record does not establish what kind of session it was"
    HOME_KINDS = _SESSION_HOMES


class SessionRestartFailed(PlatformEvent[SessionRef, SessionRestartFailedData]):
    NAME = "teleclaude.agent_runtime.session.restart_failed"
    DESCRIPTION = "An agent restart failed before the agent could resume, and the session was kept alive for inspection"
    HOME_KINDS = _SESSION_HOMES


class RuntimeSessionSourceChanged(PlatformEvent[SessionRef, RuntimeSessionSourceChangedData]):
    NAME = "teleclaude.agent_runtime.session.source_changed"
    DESCRIPTION = "A session source row changed and should be reconciled from current state"
    HOME_KINDS = _SESSION_HOMES


class RuntimeSessionStatusChanged(PlatformEvent[SessionRef, RuntimeSessionStatusData]):
    NAME = "teleclaude.agent_runtime.session.status_changed"
    DESCRIPTION = "A session's canonical runtime status changed"
    HOME_KINDS = _SESSION_HOMES


class RuntimeAgentActivityObserved(PlatformEvent[SessionRef, RuntimeAgentActivityData]):
    NAME = "teleclaude.agent_runtime.agent.activity_observed"
    DESCRIPTION = "An agent session produced an activity observation"
    HOME_KINDS = _SESSION_HOMES


class RuntimeAgentAvailabilityChanged(PlatformEvent[ComputerRef, RuntimeAgentAvailabilityData]):
    NAME = "teleclaude.agent_runtime.agent.availability_changed"
    DESCRIPTION = "Agent availability on this computer changed"


class RuntimeErrorReported(PlatformEvent[EventRef, RuntimeErrorData]):
    NAME = "teleclaude.agent_runtime.error.reported"
    DESCRIPTION = "A runtime error was reported with its existing diagnostic details"
    HOME_KINDS = _SESSION_HOMES


class RuntimeOperationSucceeded(PlatformEvent[OperationRef, RuntimeOperationOutcomeData]):
    FAMILY = _RUNTIME_OPERATION_OUTCOME_FAMILY
    STATE = LifecycleState.SUCCEEDED
    DESCRIPTION = "A durable operation completed successfully"
    HOME_KINDS = _RUNTIME_OPERATION_HOME_KINDS


class RuntimeOperationFailed(PlatformEvent[OperationRef, RuntimeOperationOutcomeData]):
    FAMILY = _RUNTIME_OPERATION_OUTCOME_FAMILY
    STATE = LifecycleState.FAILED
    DESCRIPTION = "A durable operation failed"
    HOME_KINDS = _RUNTIME_OPERATION_HOME_KINDS


class SessionBootstrapFailed(PlatformEvent[SessionRef, SessionBootstrapFailedData]):
    NAME = "teleclaude.system.session.bootstrap_failed"
    DESCRIPTION = "A session's tmux/identity bootstrap failed, stranding it before it reached active"
    HOME_KINDS = _SESSION_HOMES


class EffectiveConfigUpdated(PlatformEvent[ConfigurationRef, EffectiveConfigUpdatedData]):
    NAME = "teleclaude.config.effective.updated"
    DESCRIPTION = "Effective project configuration changed and may affect workflow runner eligibility"
    HOME_KINDS = _PROJECT_HOME


class ConfigValidationFailed(PlatformEvent[ConfigurationRef, ConfigValidationData]):
    FAMILY = CONFIG_VALIDATION_FAMILY
    STATE = LifecycleState.FAILED
    DESCRIPTION = "A configuration document on this computer does not validate and was not applied; it needs correcting"


class ConfigValidationRecovered(PlatformEvent[ConfigurationRef, ConfigValidationData]):
    FAMILY = CONFIG_VALIDATION_FAMILY
    STATE = LifecycleState.RECOVERED
    DESCRIPTION = "A configuration document that did not validate on this computer validates again"


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
    HelpDeskSessionEnded,
    PersonSessionEnded,
    SystemSessionEnded,
    UnknownSessionEnded,
    SessionRestartFailed,
    RuntimeSessionSourceChanged,
    RuntimeSessionStatusChanged,
    RuntimeAgentActivityObserved,
    RuntimeAgentAvailabilityChanged,
    RuntimeErrorReported,
    RuntimeOperationSucceeded,
    RuntimeOperationFailed,
    SessionBootstrapFailed,
    EffectiveConfigUpdated,
    ConfigValidationFailed,
    ConfigValidationRecovered,
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
