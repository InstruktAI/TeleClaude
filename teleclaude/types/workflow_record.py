"""The workflow machine's persisted record on an item - pure types, no behavior.

The record holds what the machine reads: acts as ledger entries attributed by the
sealed verbs that wrote them, effects an act committed and has not yet finished,
the launch reservation of a driver being started, and the observations (heads,
offered findings, publish intents) the review cycle needs. Phases and acts are
owned by ``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Phase(StrEnum):
    """The closed vocabulary of item phases a person or session reads."""

    PREPARATION = "preparation"
    WAITING = "waiting"
    PREPARED = "prepared"
    WORK = "work"
    READY = "ready"
    DELIVERED = "delivered"
    DESIGN = "design"


class WaitedPhase(StrEnum):
    """The phases an item can wait in; the item returns to the one it waited in."""

    PREPARATION = "preparation"
    WORK = "work"


class EmittedEvent(StrEnum):
    """The notices an emit-event effect can raise."""

    CLAIM_CHANGED = "claim_changed"
    HEAD_ADVANCED = "head_advanced"
    WAITING = "waiting"
    READY = "ready"
    DRIVER_REQUESTED = "driver_requested"


class Act(StrEnum):
    """The closed vocabulary of acts the sealed verbs record."""

    CREATE = "create"
    CLAIM = "claim"
    RELEASE = "release"
    NOTE = "note"
    INTENT_EDIT = "intent-edit"
    REVIEWED = "reviewed"
    FINDING = "finding"
    REPLY = "reply"
    PREPARED = "prepared"
    WAITING = "waiting"
    STAMP = "stamp"
    KICKBACK = "kickback"
    DECISION = "decision"
    DELIVERED = "delivered"


class ActStatus(StrEnum):
    """Whether every effect an act committed has finished."""

    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


class EffectKind(StrEnum):
    """The effects an act can commit for later completion."""

    EMIT_EVENT = "emit_event"
    END_SESSION = "end_session"
    WAKE_SESSION = "wake_session"
    START_DRIVER = "start_driver"
    RELEASE_CLAIM = "release_claim"


class LedgerEntry(BaseModel):
    """One act, attributed by the sealed verb that wrote it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int
    act: Act
    key: str
    epoch: int
    at: str
    role: str
    session_id: str
    bound: str = ""


class PendingEffect(BaseModel):
    """An effect an act committed that has not finished; ``id`` is stable across retries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    act_key: str
    kind: EffectKind
    event: EmittedEvent | None = None
    params: dict[str, str] = Field(default_factory=dict)


class LaunchReservation(BaseModel):
    """A driver being started: the key a claiming agent must present."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    phase: Phase
    requested_at: str
    requested_by: str


class WaitingRecord(BaseModel):
    """The open question a person owns, and the phase the item returns to."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    waited_phase: WaitedPhase
    person: str
    question_digest: str


class PreparedRecord(BaseModel):
    """The body revision the driver judged to be the spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: str
    session_id: str
    at: str


class StampRecord(BaseModel):
    """A stamp bound to a commit, and when the item became ready at it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha: str
    session_id: str
    ready_at: str


class StampInFlight(BaseModel):
    """The marker of a stamp invocation that is running its gates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    sha: str
    session_id: str
    started_at: str


class ObservedHead(BaseModel):
    """An integration-head commit whose notice was raised."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    branch: str
    sha: str
    at: str


class PublishIntent(BaseModel):
    """A registered push of one explicit commit as a swap of the integration ref."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    branch: str
    sha: str
    expected_tip: str
    session_id: str
    completed: bool = False
    swapped: bool = False


class OfferedFinding(BaseModel):
    """A finding a session was offered at a stop, recorded after the response was written."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    finding_key: str


class WorkflowRecord(BaseModel):
    """Everything the workflow machine persists on an item beyond the lifecycle phase."""

    model_config = ConfigDict(extra="forbid")

    claim_epoch: int = 0
    ledger: list[LedgerEntry] = Field(default_factory=list)
    act_status: dict[str, ActStatus] = Field(default_factory=dict)
    pending_effects: list[PendingEffect] = Field(default_factory=list)
    launch: LaunchReservation | None = None
    waiting: WaitingRecord | None = None
    prepared: PreparedRecord | None = None
    stamp: StampRecord | None = None
    stamp_in_flight: StampInFlight | None = None
    observed_heads: list[ObservedHead] = Field(default_factory=list)
    publish_intents: list[PublishIntent] = Field(default_factory=list)
    offered_findings: list[OfferedFinding] = Field(default_factory=list)
